from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chromium.options import ChromiumOptions

from bs4 import BeautifulSoup
import time

class BrowserController:
    def __init__(self, path_to_chrome: str = None):
        self.driver = None
        self.path_to_chrome = path_to_chrome
        
    def start_browser(self):
        options = ChromiumOptions()
        if self.path_to_chrome:
            options.binary_location = self.path_to_chrome
        self.driver = webdriver.Chrome(options=options)
        return self.driver

    def open(self, url: str):
        """Открытие страницы по URL"""
        self.driver.get(url)

    def compress_html(self, html):
        """Сжатие HTML-кода, удаление лишних пробелов и переносов строк"""
        cleaned = self._remove_scripts_and_styles(html)
        interactive_elements = self._extract_interactive_elements(cleaned)
        visible_text = self._extract_visible_text(cleaned)
        return str(interactive_elements) + "\n" + visible_text + '\n' + str(self._get_buttons_and_inputs_xpath(html))
    
    def wait(self, seconds: int):
        """Ожидание заданного количества секунд"""
        time.sleep(seconds)

    def get_html(self):
        """Получение HTML-кода текущей страницы"""
        return self.compress_html(self.driver.page_source)

    def click_element(self, xpath, by=By.XPATH):
        """
        Попытка клика по элементу, если он доступен
        :param xpath: селектор элемента
        :param by: тип селектора
        """
        try:
            self._safe_click_element(xpath, by)
        except Exception as err:
            return err

    def enter(self, xpath, text, by=By.XPATH):
        """
        Ввод текста в поле
        :param xpath: селектор элемента
        :param text: текст для ввода
        :param by: тип селектора
        """
        try:
            self._safe_enter_text(xpath, text, by)
        except Exception as err:
            return err

    def _safe_enter_text(self, selector, text, by=By.XPATH):
        """
        Ввод текста в элемент
        :param selector: XPath-селектор или другой идентификатор
        :param text: текст для ввода
        :param by: тип селектора (по умолчанию XPath)
        """
        wait_element = WebDriverWait(self.driver, 10)
        element = wait_element.until(
            EC.presence_of_element_located((by, selector))
        )
        element.clear()
        element.send_keys(text)

    def _safe_click_element(self, selector, by=By.XPATH):
        """
        Клик по элементу
        :param selector: XPath-селектор или другой идентификатор
        :param by: тип селектора (по умолчанию XPath)
        """
        wait_element = WebDriverWait(self.driver, 10)
        element = wait_element.until(
            EC.element_to_be_clickable((by, selector))
        )
        element.click()

    def close_browser(self):
        """Закрытие браузера"""
        if self.driver:
            self.driver.quit()

    @staticmethod
    def _remove_scripts_and_styles(html: str) -> str:
        """Удаление тегов <script> и <style> из HTML-кода"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')

        for script_or_style in soup(['script', 'style']):
            script_or_style.decompose()

        return str(soup)
    
    @staticmethod
    def _extract_interactive_elements(html: str) -> list:
        """Извлечение интерактивных элементов из HTML-кода"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')
        interactive_elements = []

        for tag in ['a', 'button', 'input', 'select', 'textarea']:
            for element in soup.find_all(tag):
                interactive_elements.append(str(element))

        return interactive_elements
    
    @staticmethod
    def _extract_visible_text(html: str) -> str:
        """Извлечение видимого текста из HTML-кода"""
        soup = BeautifulSoup(html, 'html.parser')
        texts = soup.stripped_strings
        visible_text = ' '.join(texts)

        return visible_text
    
    @staticmethod
    def _get_stable_xpath(element):
        """Генерация стабильного XPath с использованием уникальных атрибутов"""
        # Если есть ID - используем его (самый надежный)
        if element.get('id'):
            return f"//{element.name}[@id='{element['id']}']"
        
        # Собираем уникальные атрибуты
        attributes = []
        
        # Приоритетные атрибуты для поиска
        priority_attrs = ['name', 'type', 'placeholder', 'aria-label', 'data-testid', 'role']
        
        for attr in priority_attrs:
            if element.get(attr):
                attributes.append(f"@{attr}='{element[attr]}'")
        
        # Если нашли хорошие атрибуты - используем их
        if attributes:
            return f"//{element.name}[{' and '.join(attributes)}]"
        
        # Пробуем использовать текст для кнопок и ссылок
        if element.text.strip() and element.name in ['button', 'a', 'span', 'div']:
            text = element.text.strip()[:50]  # ограничиваем длину текста
            return f"//{element.name}[contains(text(), '{text}')]"
        
        # Последний вариант - использовать классы (менее надежно)
        if element.get('class'):
            classes = ' '.join(element['class'])
            return f"//{element.name}[contains(@class, '{element['class'][0]}')]"
        
        # Крайний случай - относительный путь по родителям
        return f"//{element.name}"

    def _get_buttons_and_inputs_xpath(self, html):
        """Извлечение кнопок и полей ввода с качественными XPath"""
        soup = BeautifulSoup(html, 'html.parser')
        elements_info = []
        
        # Расширяем список тегов для лучшего покрытия
        interactive_tags = ['button', 'input', 'a', 'textarea', 'select']
        
        for tag in interactive_tags:
            for element in soup.find_all(tag):
                # Пропускаем скрытые элементы
                if element.get('type') == 'hidden':
                    continue
                if element.get('style') and 'display:none' in element.get('style'):
                    continue
                
                element_info = {
                    'tag': tag,
                    'text': element.text.strip() if element.text else '',
                    'attributes': {k: v for k, v in element.attrs.items() if k not in ['style', 'class']},
                    'xpath': self._get_stable_xpath(element),
                    'visible_text': element.text.strip()[:100] if element.text else ''
                }
                elements_info.append(element_info)
        
        return elements_info