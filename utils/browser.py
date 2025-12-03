import time
from typing import Optional, Literal, List

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chromium.options import ChromiumOptions
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException

from bs4 import BeautifulSoup, Comment, Tag
from lxml import html as lxml_html


class BrowserController:
    """
    Контроллер браузера.

    - Запускает undetected_chromedriver.
    - Выполняет базовые действия (open / click / enter).
    - Готовит HTML к отправке ИИ:
        * get_html(raw=False) — видимый текст + краткий список интерактивных элементов;
        * get_html(raw=True)  — очищенный HTML (без скриптов/стилей);
        * get_visible_html()  — очищенный HTML ТОЛЬКО ВИДИМОЙ части страницы (для get_details/helper);
        * get_dom_chunk(...)  — выборка куска DOM по CSS/xpath.
    """

    def __init__(
        self,
        path_to_chrome: Optional[str] = None,
        default_timeout: int = 10,
    ):
        self.driver = None
        self.path_to_chrome = path_to_chrome
        self.default_timeout = default_timeout

    def start_browser(self):
        """Запуск браузера с заданным бинарником (если указан)."""
        options = ChromiumOptions()
        if self.path_to_chrome:
            options.binary_location = self.path_to_chrome

        self.driver = uc.Chrome(options=options)
        return self.driver

    def close_browser(self):
        """Закрытие браузера."""
        if self.driver:
            self.driver.quit()
            self.driver = None

    def open(self, url: str):
        """Открытие страницы по URL."""
        if not self.driver:
            raise RuntimeError("Browser is not started. Call start_browser() first.")
        self.driver.get(url)

    def click_element(self, xpath: str, by: By = By.XPATH, **kwargs):
        """
        Клик по элементу.

        Возвращает None при успехе, либо Exception при ошибке.
        """
        if not self.driver:
            raise RuntimeError("Browser is not started. Call start_browser() first.")

        try:
            self._safe_click_element(xpath, by=by, timeout=kwargs.get("timeout"))
        except Exception as err:
            return err

    def enter(self, xpath: str, text: str, by: By = By.XPATH):
        """
        Ввод текста в поле.

        Возвращает None при успехе, либо Exception при ошибке.
        """
        if not self.driver:
            raise RuntimeError("Browser is not started. Call start_browser() first.")

        try:
            self._safe_enter_text(xpath, text, by=by)
        except Exception as err:
            return err

    def get_raw_html(self) -> str:
        """Сырой HTML текущей страницы."""
        if not self.driver:
            return ""
        return self.driver.page_source or ""

    def get_visible_html(self, max_chars: int = 150000) -> str:
        """
        Очищенный HTML ТОЛЬКО ВИДИМОЙ части страницы:
        - удалены script/style/noscript/svg/head;
        - удалены комментарии;
        - удалены элементы с hidden/aria-hidden/display:none/visibility:hidden/opacity:0.
        """
        html = self.get_raw_html()
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all(["script", "style", "noscript", "svg", "head"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        to_remove: List[Tag] = []
        for tag in soup.find_all(True):
            if not isinstance(tag, Tag):
                continue
            attrs = tag.attrs if isinstance(getattr(tag, "attrs", None), dict) else {}
            style_raw = attrs.get("style") or ""
            style = style_raw.lower().replace(" ", "")
            hidden_attr = "hidden" in attrs
            aria_hidden = attrs.get("aria-hidden") == "true"
            if (
                hidden_attr
                or aria_hidden
                or "display:none" in style
                or "visibility:hidden" in style
                or "opacity:0" in style
            ):
                to_remove.append(tag)

        for tag in to_remove:
            tag.decompose()

        cleaned = str(soup)
        cleaned = self._normalize_whitespace(cleaned)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + "\n[...TRUNCATED...]"
        return cleaned

    def get_html(self, raw: bool = False, max_chars: int = 60000) -> str:
        """
        Подготовленный HTML / текст для LLM.

        raw = False:
            - URL и заголовок
            - компактный видимый текст
            - краткий список интерактивных элементов
          → используется как [CURRENT PAGE STATE] для планирующей модели.

        raw = True:
            - URL и заголовок
            - очищенный HTML (без script/style/noscript и т.п.), БЕЗ фильтра по видимости.
          → удобно как общий контекст при необходимости.
        """
        if not self.driver:
            return ""

        html = self.get_raw_html()
        url = (self.driver.current_url or "").strip()
        title = (self.driver.title or "").strip()

        if raw:
            cleaned = self._remove_scripts_and_styles(html)
            cleaned = self._normalize_whitespace(cleaned)
            if len(cleaned) > max_chars:
                cleaned = cleaned[:max_chars] + "\n[...TRUNCATED...]"
            return f"{url}\n[TITLE]: {title}\n[HTML]:\n{cleaned}"

        visible_text = self._extract_visible_text(html, max_chars=max_chars // 2)
        interactive_summary = self._summarize_interactive_elements(
            html, max_items=80, max_chars=max_chars // 2
        )

        result_parts: List[str] = [
            url,
            f"[TITLE]: {title}",
            "",
            "[VISIBLE TEXT]:",
            visible_text,
            "",
            "[INTERACTIVE ELEMENTS]:",
            interactive_summary,
        ]
        combined = "\n".join(result_parts)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n[...TRUNCATED...]"
        return combined

    def get_dom_chunk(
        self,
        mode: Literal["css", "xpath"] = "css",
        selector: str = "body",
        max_chars: int = 8000,
    ) -> str:
        """
        Возвращает фрагмент DOM (для функции get_dom_chunk).

        mode="css"   — selector как CSS-селектор (BeautifulSoup).
        mode="xpath" — selector как XPath (lxml).
        """
        html = self.get_raw_html()
        if not html:
            return ""

        if mode == "css":
            soup = BeautifulSoup(html, "html.parser")
            nodes = soup.select(selector)
            if not nodes:
                return f"[DOM CHUNK] No elements for CSS selector: {selector}"
            chunk_html = "".join(str(n) for n in nodes)
        else:
            try:
                tree = lxml_html.fromstring(html)
                nodes = tree.xpath(selector)
            except Exception as e:
                return f"[DOM CHUNK] XPath parse error: {e}"
            if not nodes:
                return f"[DOM CHUNK] No elements for XPath: {selector}"
            chunk_html = "".join(
                lxml_html.tostring(node, encoding="unicode") for node in nodes
            )

        cleaned = self._remove_scripts_and_styles(chunk_html)
        cleaned = self._normalize_whitespace(cleaned)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars] + "\n[...TRUNCATED...]"

        return f"[DOM CHUNK mode={mode} selector={selector}]:\n{cleaned}"

    def _safe_click_element(self, selector, by=By.XPATH, **kwargs):
        """
        Клик по элементу.

        :param selector: XPath-селектор или другой идентификатор
        :param by: тип селектора (по умолчанию XPath)
        """
        wait_element = WebDriverWait(self.driver, 10)
        try:
            element = wait_element.until(
                EC.element_to_be_clickable((by, selector))
            )
        except TimeoutException as e:
            # Элемент так и не стал кликабельным
            raise TimeoutException(f"Element not clickable by {by}='{selector}'") from e

        try:
            # Обычный клик
            element.click()
        except (ElementClickInterceptedException, Exception):
            # Фолбэки для сложных SPA (типа Яндекс Лавки)
            try:
                # 1) Скроллим к элементу
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                    element
                )
                # 2) Пробуем кликнуть через ActionChains
                try:
                    ActionChains(self.driver).move_to_element(element).click().perform()
                except Exception:
                    # 3) Жёсткий JS-клик
                    self.driver.execute_script("arguments[0].click();", element)
            except Exception as e:
                raise ElementClickInterceptedException(
                    f"Failed to click element by {by}='{selector}' even with JS fallback: {e}"
                )

    def _safe_enter_text(
        self,
        selector: str,
        text: str,
        by: By = By.XPATH,
    ):
        """Ожидает поле ввода и печатает в него текст."""
        wait = WebDriverWait(self.driver, self.default_timeout)
        try:
            element = wait.until(EC.presence_of_element_located((by, selector)))
            element.clear()
            element.send_keys(text)
        except TimeoutException as e:
            raise TimeoutException(f"Input element not found by {by}='{selector}'") from e

    @staticmethod
    def _remove_scripts_and_styles(html: str) -> str:
        """Удаляет script/style/noscript/svg/head и комментарии."""
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all(["script", "style", "noscript", "svg", "head"]):
            tag.decompose()

        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        return str(soup)

    @staticmethod
    def _normalize_whitespace(text: str) -> str:
        return " ".join(text.split())

    def _extract_visible_text(self, html: str, max_chars: int = 20000) -> str:
        """
        Извлекает видимый текст страницы:
        - удаляет мусорные теги и комментарии;
        - убирает заведомо скрытые элементы (hidden, aria-hidden, display:none и т.п.).
        """
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all(["script", "style", "noscript", "svg", "head"]):
            tag.decompose()
        for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        to_remove: List[Tag] = []
        for tag in soup.find_all(True):
            if not isinstance(tag, Tag):
                continue
            attrs = tag.attrs if isinstance(getattr(tag, "attrs", None), dict) else {}
            style_raw = attrs.get("style") or ""
            style = style_raw.lower().replace(" ", "")
            hidden_attr = "hidden" in attrs
            aria_hidden = attrs.get("aria-hidden") == "true"
            if (
                hidden_attr
                or aria_hidden
                or "display:none" in style
                or "visibility:hidden" in style
                or "opacity:0" in style
            ):
                to_remove.append(tag)

        for tag in to_remove:
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = self._normalize_whitespace(text)
        if len(text) > max_chars:
            text = text[:max_chars] + " [...TRUNCATED...]"
        return text

    def _summarize_interactive_elements(
        self,
        html: str,
        max_items: int = 80,
        max_chars: int = 20000,
    ) -> str:
        """
        Краткий список интерактивных элементов:
        - ссылки <a>
        - кнопки <button>
        - элементы с role=button/link/checkbox/tab/menuitem/row/option
        - элементы с data-tooltip / data-label
        """
        soup = BeautifulSoup(html, "html.parser")
        lines: List[str] = []

        def add_line(prefix: str, tag):
            desc_parts = []

            text = (tag.get_text(strip=True) or "")[:80]
            aria = (tag.get("aria-label") or "")[:80]
            tooltip = (tag.get("data-tooltip") or "")[:80]
            label = (tag.get("data-label") or "")[:80]
            title = (tag.get("title") or "")[:80]
            href = (tag.get("href") or "")[:120]

            if aria:
                desc_parts.append(f"aria={aria}")
            if tooltip:
                desc_parts.append(f"tooltip={tooltip}")
            if label:
                desc_parts.append(f"label={label}")
            if title:
                desc_parts.append(f"title={title}")
            if text and text not in (aria, tooltip, label, title):
                desc_parts.append(f"text={text}")
            if href:
                desc_parts.append(f"href={href}")

            if not desc_parts:
                return

            desc = " | ".join(desc_parts)
            lines.append(f"{prefix}: {desc}")

        # Ссылки
        for a in soup.find_all("a"):
            if len(lines) >= max_items:
                break
            add_line("LINK", a)

        for btn in soup.find_all("button"):
            if len(lines) >= max_items:
                break
            add_line("BUTTON", btn)

        roles = ["button", "link", "checkbox", "tab", "menuitem", "row", "option"]
        for role in roles:
            for el in soup.find_all(attrs={"role": role}):
                if len(lines) >= max_items:
                    break
                add_line(f"ROLE[{role}]", el)
            if len(lines) >= max_items:
                break

        for el in soup.find_all(attrs={"data-tooltip": True}):
            if len(lines) >= max_items:
                break
            add_line("TOOLTIP", el)

        for el in soup.find_all(attrs={"data-label": True}):
            if len(lines) >= max_items:
                break
            add_line("LABEL", el)

        summary = "\n".join(lines) if lines else "[no interactive elements summary]"
        if len(summary) > max_chars:
            summary = summary[:max_chars] + "\n[...TRUNCATED...]"
        return summary
