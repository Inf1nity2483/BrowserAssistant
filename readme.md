Browser assistant, написанный на python, с использованием библиотек selenium, openai

# ENV

Создайте файл .env
Введите значение env-переменных
```
open_ai_token: str //example sk-proj-Q41nWDOnS9w1CVWzV-S9OONbdVQuvp_ksPd9JAGhKkxbJw6FLzPfF7Ie68O5UqFJuXnnfl9vFKT3BlbkFJg49GzqQsUMNYL9UfUdt-qu8O1QrQWlxAS6edipCFc21A_csmD1iCXHERso_RQkE26kkf
model: str //example gpt-4o-mini
```

# Запуск
`python -m venv Venv`

`source .\Venv\Scripts\bin` или `.\Venv\Scripts\activate` для win

`pip install -r .\requirements.txt`

`python main.py`

# Продвинутые паттерны
- Обработка ошибок 
При возникновении ошибки (валидация модели, неудачный клик и пр.), ошибка отправляется в ИИ для анализа и получения дальнейший действий.

- Security layer 
ИИ спрашивает у пользователя подтверждение, перед возможным деструктивным действием. 
