from openai import OpenAI

class AssistantAI():
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.history = []
        self.promt = self.load_promt()

    def load_promt(self):
        with open('./promt.txt', 'r', encoding='utf-8') as file:
            promt = file.read()
            self.history.append({
                "role": "system",
                "content": promt
            })
            return promt

    def request(self, data: list):
        response = self.client.chat.completions.create(
            model=self.model,
            messages=data
        )

        bot_reply = response.choices[0].message.content
        return bot_reply

    def chat(self, msg: str, role: str = "user"):
        self.history.append({
            "role": role,
            "content": msg
        })

        response = self.request(data=self.history)

        if role == 'system':
            self.history = self.history[:-1]

        return response
    
    def save_response(self, msg: str):
        self.history.append({
            "role": "assistant",
            "content": msg
        })

    def delete_response(self, msg: str):
        for i in range(len(self.history)-1, -1, -1):
            if self.history[i]['role'] == 'assistant' and self.history[i]['content'] == msg:
                self.history.pop(i)
                break