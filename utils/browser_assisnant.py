import json
import re

from utils.browser import BrowserController
from utils.assistant import AssistantAI
import models.models as models


class BrowserAssistant:
    def __init__(self, config, path_to_chrome: str = None):
        self.browser_controller = BrowserController(
            path_to_chrome=path_to_chrome
        )
        self.assistant = AssistantAI(
            api_key=config.open_ai_token,
            model=config.model,
        )

    def _fix_trailing_commas(self, text: str) -> str:
        """
        Грубый, но полезный фикс висячих запятых в JSON.
        Заменяет ', }' и ', ]' на '}'/']', не трогая содержимое строк.
        """
        return re.sub(r',(\s*[\]}])', r'\1', text)

    def start(self):
        self.browser_controller.start_browser()

        model: models.AssistantResponse | None = None
        error_retries = 0
        max_error_retries = 5

        msg = ""
        failed_xpaths: dict[str, int] = {}
        max_xpath_retries = 2

        while True:
            current_state = self.browser_controller.get_html()
            user_input = ""

            if model and model.missing_data and len(model.missing_data) > 0:
                print("📝 Требуется ввод данных:")
                for item in model.missing_data:
                    print(f" - {item.question}")
                user_input = input("\n(enter `q` to exit)>>> ")
                if user_input.lower() == "q":
                    self.browser_controller.close_browser()
                    break

                fields = ", ".join(m.field for m in model.missing_data)
                msg = (
                    f"Пользователь ввёл данные для полей: {fields}. "
                    f"Сырый ответ пользователя: {user_input}"
                )
                error_retries = 0

            elif model is None or model.status in ["done", "error"]:
                if model and model.status == "done":
                    print(f"✅ Задача выполнена: {model.current_goal}")
                    user_input = input("Скажите, что делать далее: ")
                    continue

                if model and model.status == "error":
                    error_retries += 1
                    print(f"⚠️ Ошибка ({error_retries}/{max_error_retries}): {model.current_goal}")
                    if error_retries >= max_error_retries:
                        print("❌ Лимит попыток исчерпан")
                        break

                    msg = f"""[SYSTEM RETRY {error_retries}/{max_error_retries}]
Предыдущая ошибка: {model.current_goal}
ОБЯЗАТЕЛЬНО выполни get_details для анализа текущей страницы:
{{
  "function": "get_details",
  "args": {{"prompt": "Опиши, что сейчас на странице. Найди все интерактивные элементы."}},
  "reason": "Анализ после ошибки"
}}
Верни status="in_progress" с action_sequence."""
                else:
                    user_input = input("(enter `q` to exit)>>> ")
                    if user_input.lower() == "q":
                        self.browser_controller.close_browser()
                        break
                    msg = user_input
                    error_retries = 0

            if msg:
                full_message = f"{msg}\n\n[CURRENT PAGE STATE]:\n{current_state}"
            else:
                full_message = f"[CURRENT PAGE STATE]:\n{current_state}"

            response = self.assistant.chat(full_message)
            msg = ""

            cleaned_response = self._fix_trailing_commas(response)

            try:
                model = models.AssistantResponse.model_validate_json(cleaned_response)
            except Exception as e:
                print(f"❌ Ошибка парсинга: {e}")
                msg = (
                    "[SYSTEM] Ошибка парсинга JSON. Убери висячие запятые и другие "
                    "некорректные конструкции. Верни ВАЛИДНЫЙ JSON по описанию в промте."
                )
                continue

            if model.missing_data and len(model.missing_data) > 0:
                continue

            if not model.action_sequence:
                continue

            for action in model.action_sequence:
                print(f"▶️ {action.function} | {action.reason if action.reason else '...'}")

                try:
                    if action.function == "open":
                        self.browser_controller.open(**action.args)
                        msg += f"\n[PAGE LOADED]: {self.browser_controller.driver.current_url}\n"
                        msg += self.browser_controller.get_html()

                    elif action.function == "click":
                        xpath = action.args.get("xpath", "")

                        if xpath in failed_xpaths and failed_xpaths[xpath] >= max_xpath_retries:
                            msg += (
                                f"\n[SYSTEM CRITICAL] xpath {xpath} уже провалился "
                                f"{failed_xpaths[xpath]} раз!\n"
                            )
                            msg += (
                                "ОБЯЗАТЕЛЬНО вызови get_details с СОВЕРШЕННО ДРУГИМ запросом "
                                "(по тексту/aria-label/data-tooltip вместо жёсткой структуры DOM).\n"
                            )
                            print(f"🚫 Блокировка xpath после {max_xpath_retries} неудач")
                            continue

                        error = self.browser_controller.click_element(**action.args)
                        if error:
                            failed_xpaths[xpath] = failed_xpaths.get(xpath, 0) + 1
                            msg += f"\n[CLICK ERROR #{failed_xpaths[xpath]}]: {error}\n"
                            msg += f"Элемент не найден по xpath: {xpath}\n"
                            if failed_xpaths[xpath] >= max_xpath_retries:
                                msg += "⚠️ КРИТИЧЕСКОЕ ПРЕДУПРЕЖДЕНИЕ: Этот xpath не работает!\n"
                                msg += "В СЛЕДУЮЩЕМ ОТВЕТЕ:\n"
                                msg += "1. Вызови get_details с ДРУГОЙ стратегией поиска\n"
                                msg += "2. НЕ используй xpath со структурой //tr[3]//div — он НЕ РАБОТАЕТ\n"
                                msg += "3. Ищи элементы по aria-label, data-tooltip или видимому тексту\n"
                        else:
                            if xpath in failed_xpaths:
                                del failed_xpaths[xpath]
                            msg += f"\n[CLICK OK]: {action.args}\n"
                            msg += self.browser_controller.get_html()

                    elif action.function == "enter":
                        error = self.browser_controller.enter(**action.args)
                        if error:
                            msg += f"\n[ENTER ERROR]: {error}\n"
                        else:
                            msg += f"\n[ENTER OK]: {action.args}\n"
                            msg += self.browser_controller.get_html()

                    elif action.function == "get":
                        html = self.browser_controller.get_html(raw=True)
                        msg += f"\n[FULL HTML]:\n{html}\n"

                    elif action.function == "get_dom_chunk":
                        chunk = self.browser_controller.get_dom_chunk(**action.args)
                        msg += f"\n[DOM CHUNK]:\n{chunk}\n"

                    elif action.function == "get_details":
                        visible_html = self.browser_controller.get_visible_html()
                        result = self.assistant.analyze_html_chunked(
                            html=visible_html,
                            max_chunk_chars=150000,
                            **action.args,
                        )

                        msg += f"\n[GET_DETAILS RESULT]:\n{result}\n"

                        try:
                            data = json.loads(result)
                        except Exception as e:
                            msg += f"\n[SYSTEM] Не удалось распарсить JSON get_details: {e}\n"
                        else:
                            found = bool(data.get("found"))
                            elements = data.get("elements") or []
                            if found and elements:
                                best = elements[0]
                                xpath = best.get("xpath")
                                action_type = (best.get("action") or "click").lower()
                                msg += (
                                    "\n[SYSTEM] get_details нашёл подходящий элемент.\n"
                                    "В СЛЕДУЮЩЕМ ОТВЕТЕ ОБЯЗАТЕЛЬНО добавь в action_sequence "
                                    f"ПЕРВЫМ действием функцию \"{action_type}\" с этим xpath: {xpath}.\n"
                                    "НЕ вызывай get_details ещё раз для этой же подзадачи и НЕ ставь status=\"error\".\n"
                                )
                            else:
                                msg += (
                                    "\n[SYSTEM] get_details НЕ нашёл элемент по запросу.\n"
                                    "НЕ ставь status=\"error\". Выполни ещё один get_details с более точным "
                                    "или другим prompt, либо измени стратегию (другая часть страницы).\n"
                                )
                        msg += (
                            "\n[SYSTEM] ОБЯЗАТЕЛЬНО используй xpath из [GET_DETAILS RESULT] выше, "
                            "если found=true!\n"
                        )

                    elif action.function == "helper":
                        visible_html = self.browser_controller.get_visible_html()
                        helper_prompt = action.args.get("prompt", "")
                        extra = action.args.get("extra")

                        result = self.assistant.call_helper(
                            helper_prompt=helper_prompt,
                            html=visible_html,
                            extra=extra,
                        )
                        msg += f"\n[HELPER RESULT]:\n{result}\n"

                    elif action.function == "save_response":
                        self.assistant.save_response(**action.args)
                        msg += f"\n[SAVED]: {action.args.get('msg', '')[:100]}\n"

                    elif action.function == "delete_response":
                        self.assistant.delete_response(**action.args)
                        msg += "\n[DELETED]\n"

                    elif action.function == 'waiting_user_input':
                        msg += f'user input: {input()}'

                    else:
                        msg += f"\n[UNKNOWN FUNCTION]: {action.function}\n"

                except Exception as e:
                    msg += f"\n[EXCEPTION in {action.function}]: {e}\n"
                    print(f"❌ Exception: {e}")

            if model.status == "in_progress" and model.action_sequence:
                error_retries = 0
