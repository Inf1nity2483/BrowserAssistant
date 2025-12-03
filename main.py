from settings.config import config
from utils.browser_assisnant import BrowserAssistant

def main():
    # Если нужно указать путь к Chrome, передайте его в конструктор BrowserAssistant
    # path_to_chrome="C:/Path/To/Your/Chrome.exe"
    ba = BrowserAssistant(config, path_to_chrome="./chrome-win64/chrome.exe")
    ba.start()

if __name__ == "__main__":
    main()