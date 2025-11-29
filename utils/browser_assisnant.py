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
            model=config.model
        )

    def start(self):
        self.browser_controller.start_browser()
        model = None

        try:
            while 1:
                if model and model.status == "waiting_user_input":
                    for i in model.missing_data:
                        print(i.question)
                user_input = input(">>> ")
                while 1:
                    if user_input:
                        response = self.assistant.chat(user_input)
                        user_input = None
                    else:
                        response = self.assistant.chat(msg, role="system")
                    msg = ''

                    try:
                        model = models.AssistantResponse.model_validate_json(response)
                    except Exception as e:
                        msg = f"Error parsing assistant response: {e}"
                        continue

                    try:

                        for action in model.action_sequence:
                            print(f'func - {action.function} | reason - {action.reason}')
                            if action.function == "open":
                                self.browser_controller.open(**action.args)
                                msg += self.browser_controller.get_html()
                                continue
                            elif action.function == "click":
                                error = self.browser_controller.click_element(**action.args)
                                if error:
                                    msg += f"Error during clicking element: {error}"
                                    break
                                msg += self.browser_controller.get_html()
                                continue
                            elif action.function == "enter":
                                error = self.browser_controller.enter(**action.args)
                                if error:
                                    msg += f"Error during entering text: {error}"
                                    break
                                msg += self.browser_controller.get_html()
                                continue
                            elif action.function == "get":
                                msg += self.browser_controller.get_html()
                                continue
                            elif action.function == "wait":
                                self.browser_controller.wait(**action.args)
                                msg += self.browser_controller.get_html()
                                continue
                            elif action.function == "save_response":
                                self.assistant.save_response(**action.args)
                                continue
                            elif action.function == "delete_response":
                                self.assistant.delete_response(**action.args)
                                continue
                            else:
                                msg += "Unknown action:" + str(action.function)
                                break
                            
                        if model.status != "in_progress":
                            break

                    except Exception as e:
                        msg += f"Error during action execution: {e}"
                        continue
        finally:
            self.browser_controller.driver.quit()