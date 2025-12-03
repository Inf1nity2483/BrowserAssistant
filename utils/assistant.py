import time
import json
import re
from typing import Optional, List

from httpx import Client, Proxy
from openai import OpenAI, RateLimitError
from bs4 import BeautifulSoup, Comment
from lxml import etree


class AssistantAI:
    """
    Обёртка над OpenAI + вспомогательные методы анализа HTML.

    Режимы:
    - планирующая модель (chat);
    - анализатор HTML для get_details (analyze_html / analyze_html_chunked);
    - вторая модель-помощник (call_helper), которая всегда отвечает JSON.
    """

    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(
            api_key=api_key,
            http_client=Client(proxy=Proxy("http://73.235.88.231:1194"))
        )
        self.model = model
        self.history: list[dict] = []
        self.promt = self.load_promt()

    # ==========================
    # Базовый чат
    # ==========================

    def load_promt(self) -> str:
        with open("./promt.txt", "r", encoding="utf-8") as file:
            promt = file.read()
        self.history.append(
            {
                "role": "system",
                "content": promt,
            }
        )
        return promt

    def request(self, messages: list[dict]) -> str:
        while True:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                )
                break
            except RateLimitError:
                print("Rate limit exceeded. Waiting for 60 seconds before retrying...")
                time.sleep(60)

        bot_reply = response.choices[0].message.content
        return bot_reply

    def chat(self, msg: str, role: str = "user") -> str:
        self.history.append(
            {
                "role": role,
                "content": msg,
            }
        )
        response = self.request(self.history)
        self.history.append(
            {
                "role": "assistant",
                "content": response,
            }
        )
        if len(self.history) > 10:
            self.history = self.history[:2] + self.history[4:]
        return response

    def save_response(self, msg: str):
        self.history.append(
            {
                "role": "assistant",
                "content": msg,
            }
        )

    def delete_response(self, msg: str):
        for i in range(len(self.history) - 1, -1, -1):
            if (
                self.history[i]["role"] == "assistant"
                and self.history[i]["content"] == msg
            ):
                self.history.pop(i)
                break

    def _get_helper_system_prompt(self) -> str:
        return """
Ты — вспомогательный ИИ-помощник для другой модели.

Тебе приходят:
- ПОДРОБНОЕ текстовое описание задачи (prompt);
- очищенный HTML ВИДИМОЙ части текущей страницы (без скрытых блоков, скриптов и стилей);
- дополнительный JSON-объект extra (опционально).

ТВОЯ ЗАДАЧА: понять задачу и вернуть СТРОГИЙ JSON-ОБЪЕКТ.
НЕ пиши ничего, кроме одного JSON-объекта.

Примеры допустимых ответов:
- {"status": "found", "xpath": "...", "reason": "..."}
- {"status": "done", "description": "письмо 1 — спам, т.к. ...", "spam_indices": [0]}
- {"status": "error", "message": "Не удалось однозначно определить ..."}

ЖЁСТКИЕ ПРАВИЛА:
1. Всегда возвращай ОДИН JSON-объект верхнего уровня.
2. Не добавляй поясняющий текст до или после JSON.
3. Поле "status" ОБЯЗАТЕЛЬНО.
4. НИКАКИХ висячих запятых, комментариев и прочих не-JSON конструкций.
"""

    def call_helper(self, helper_prompt: str, html: str, extra: Optional[dict] = None) -> str:
        """
        Вызов второй ИИ-модели-помощника.

        helper_prompt — подробный текстовый prompt.
        html          — очищенный HTML ВИДИМОЙ части текущей страницы.
        extra         — дополнительный JSON (опционально).
        Возвращает строку с JSON-ответом помощника.
        """
        system_prompt = self._get_helper_system_prompt()

        parts: List[str] = [
            f"ЗАДАЧА (от другой модели):\n{helper_prompt}",
            "\n[VISIBLE HTML CONTEXT]:\n",
            html,
        ]
        if extra is not None:
            parts.append("\n[EXTRA]:\n")
            parts.append(json.dumps(extra, ensure_ascii=False))

        user_message = "\n".join(parts)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return self.request(messages)

    def _get_analysis_system_prompt(self) -> str:
        return """
Ты — анализатор HTML. Твоя задача — по описанию запроса найти подходящие элементы
в ОЧИЩЕННОЙ ВИДИМОЙ части страницы и вернуть их xpath.

ФОРМАТ ОТВЕТА (СТРОГО JSON-ОБЪЕКТ):

{
  "found": true/false,
  "elements": [
    {
      "description": "видимый текст + пояснение, что это за элемент",
      "xpath": "строка xpath",
      "action": "click" | "enter" | null
    }
  ],
  "page_context": "где мы на странице (область интерфейса)",
  "meta": { "chunk_index": 1, "total_chunks": 3 }  // опционально
}

ЖЁСТКИЕ ПРАВИЛА:
1. Если НЕ нашёл подходящие элементы → "found": false и "elements": [].
2. Никогда НЕ ставь "found": true с пустым "elements".
3. Если есть сомнения — ставь "found": false.
4. Каждый элемент в "elements" обязан иметь ПОНЯТНОЕ "description" и корректный "xpath".
5. НИКАКИХ висячих запятых в твоём JSON.
"""

    def _clean_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["script", "style", "noscript", "svg", "head", "meta", "link"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()
        result = str(soup)
        result = re.sub(r"\s+", " ", result)
        return result

    def _extract_with_lxml(self, html: str) -> str:
        """Извлекает краткий список интерактивных элементов (по видимой части)."""
        try:
            parser = etree.HTMLParser()
            tree = etree.fromstring(html.encode("utf-8", errors="ignore"), parser)
        except Exception as e:
            return f"[PARSE ERROR: {e}]"

        def is_likely_visible(el) -> bool:
            if el.get("hidden") is not None:
                return False
            if el.get("aria-hidden") == "true":
                return False
            style = (el.get("style") or "").lower()
            style_comp = style.replace(" ", "")
            if "display:none" in style_comp:
                return False
            if "visibility:hidden" in style_comp:
                return False
            if "opacity:0" in style_comp:
                return False
            classes = (el.get("class") or "").lower()
            hidden_indicators = ["hidden", "hide", "invisible", "collapsed", "closed"]
            if any(h in classes for h in hidden_indicators):
                visible_indicators = ["show", "visible", "active", "open", "expanded"]
                if not any(v in classes for v in visible_indicators):
                    return False
            return True

        lines: List[str] = ["[INTERACTIVE ELEMENTS - VISIBLE ONLY]"]

        # Ссылки
        links = tree.xpath("//a[@href]")
        if links:
            lines.append("\n=== LINKS ===")
            count = 0
            for el in links:
                if not is_likely_visible(el):
                    continue
                count += 1
                if count > 30:
                    break
                href = (el.get("href") or "")[:60]
                text = "".join(el.itertext()).strip()[:40]
                aria = (el.get("aria-label") or "")
                label = (el.get("data-label") or "")
                desc = aria or label or text or href
                if not desc:
                    continue
                xpath = self._make_xpath_lxml(el)
                lines.append(f" • {desc}")
                lines.append(f" xpath: {xpath}")

        # Кнопки role=button
        buttons = tree.xpath('//*[@role="button"]')
        if buttons:
            lines.append("\n=== BUTTONS (role=button) ===")
            count = 0
            for el in buttons:
                if not is_likely_visible(el):
                    continue
                count += 1
                if count > 25:
                    break
                aria = (el.get("aria-label") or "")
                tooltip = (el.get("data-tooltip") or "")
                text = "".join(el.itertext()).strip()[:40]
                desc = aria or tooltip or text
                if not desc:
                    continue
                xpath = self._make_xpath_lxml(el)
                lines.append(f" • {desc}")
                lines.append(f" xpath: {xpath}")

        # Чекбоксы
        checkboxes = tree.xpath('//*[@role="checkbox"]')
        if checkboxes:
            lines.append("\n=== CHECKBOXES ===")
            count = 0
            for el in checkboxes:
                if not is_likely_visible(el):
                    continue
                count += 1
                if count > 15:
                    break
                aria = el.get("aria-label", f"checkbox_{count}")
                checked = el.get("aria-checked", "false")
                xpath = self._make_xpath_lxml(el)
                lines.append(f" • {aria} (checked={checked})")
                lines.append(f" xpath: {xpath}")

        # Строки с role=row
        rows = tree.xpath('//*[@role="row"]')
        if rows:
            lines.append("\n=== ROWS (possible emails/items) ===")
            count = 0
            for el in rows:
                if not is_likely_visible(el):
                    continue
                count += 1
                if count > 20:
                    break
                text = "".join(el.itertext()).strip()[:80]
                if len(text) < 5:
                    continue
                xpath = self._make_xpath_lxml(el)
                lines.append(f" • row_{count}: {text}")
                lines.append(f" xpath: {xpath}")

        return "\n".join(lines)

    def _escape_xpath(self, value: str) -> str:
        if "'" not in value:
            return value
        if '"' not in value:
            return value
        return value.replace("'", "")

    def _make_xpath_lxml(self, el) -> str:
        if el.get("id"):
            return f"//*[@id='{el.get('id')}']"
        if el.get("data-label"):
            return f"//*[@data-label='{self._escape_xpath(el.get('data-label'))}']"
        if el.get("data-tooltip"):
            return f"//*[@data-tooltip='{self._escape_xpath(el.get('data-tooltip'))}']"
        if el.get("aria-label"):
            return f"//*[@aria-label='{self._escape_xpath(el.get('aria-label'))}']"
        if el.get("name"):
            return f"//{el.tag}[@name='{el.get('name')}']"
        if el.tag == "a" and el.get("href"):
            href = el.get("href")
            if len(href) < 60 and "'" not in href:
                return f"//a[@href='{href}']"
        if el.get("role"):
            role = el.get("role")
            text = "".join(el.itertext()).strip()[:25]
            if text and "'" not in text:
                return f"//*[@role='{role}'][contains(., '{text}')]"
            return f"//*[@role='{role}']"
        text = "".join(el.itertext()).strip()[:25]
        if text and "'" not in text and len(text) > 2:
            return f"//{el.tag}[contains(., '{text}')]"
        return self._build_absolute_xpath(el)

    def _build_absolute_xpath(self, el) -> str:
        parts = []
        current = el
        while current is not None and getattr(current, "tag", None) is not None:
            if current.get("id"):
                parts.insert(0, f"//*[@id='{current.get('id')}']")
                break
            parent = current.getparent()
            if parent is None:
                parts.insert(0, f"/{current.tag}")
            else:
                siblings = [c for c in parent if c.tag == current.tag]
                if len(siblings) == 1:
                    parts.insert(0, f"/{current.tag}")
                else:
                    index = siblings.index(current) + 1
                    parts.insert(0, f"/{current.tag}[{index}]")
            current = parent
        return "".join(parts) if parts else f"//{getattr(el, 'tag', 'div')}"

    def analyze_html(self, html: str, prompt: str) -> str:
        """
        Анализирует ОДИН чанк ОЧИЩЕННОГО ВИДИМОГО HTML.
        Возвращает строку с JSON (как вернула модель).
        """
        interactive_summary = self._extract_with_lxml(html)
        cleaned_html = self._clean_html(html)

        max_chars = 60000
        if len(cleaned_html) > max_chars:
            cleaned_html = cleaned_html[:max_chars] + "\n[...TRUNCATED...]"

        system_prompt = self._get_analysis_system_prompt()
        user_message = f"ЗАДАЧА: {prompt}\n\n{interactive_summary}\n\n[HTML]:\n{cleaned_html}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return self.request(messages)

    def analyze_html_chunked(
        self,
        html: str,
        prompt: str,
        max_chunk_chars: int = 100000,
        **kwargs
    ) -> str:
        """
        Режет большой HTML на чанки и по очереди вызывает analyze_html.
        Как только находит found=true и непустой elements — возвращает этот результат.
        Если нигде не найдено — возвращает found=false с описанием.
        """
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")

        chunks: List[str] = []
        for i in range(0, len(html), max_chunk_chars):
            chunks.append(html[i : i + max_chunk_chars])

        total = len(chunks)
        for idx, chunk_html in enumerate(chunks, start=1):
            chunk_prompt = f"{prompt} (чанк {idx}/{total})"
            raw_response = self.analyze_html(html=chunk_html, prompt=chunk_prompt)

            try:
                data = json.loads(raw_response)
            except Exception:
                continue

            if not isinstance(data, dict):
                continue

            found = bool(data.get("found"))
            elements = data.get("elements") or []

            if found and elements:
                meta = data.get("meta") or {}
                meta["chunk_index"] = idx
                meta["total_chunks"] = total
                data["meta"] = meta
                return json.dumps(data, ensure_ascii=False)

        not_found = {
            "found": False,
            "elements": [],
            "page_context": "Элемент по запросу не найден ни в одном чанке",
        }
        return json.dumps(not_found, ensure_ascii=False)
