from automation_engine import AutomationService, Comment, Message


class PrintPlatform:
    def reply_to_comment(self, **kwargs): print("COMMENT REPLY:", kwargs)
    def send_dm(self, **kwargs): print("DM:", kwargs)


service = AutomationService.open()
service.create_automation(automation_id="pricing", workspace_id="acme", keyword="pricing",
    reply_text="Sent you a DM!", prompt_text="What's your email address?",
    link_text="Thanks! Here's your link: https://example.com/pricing")
platform = PrintPlatform()
service.on_comment(Comment("c-event-1", "acme", "instagram", "comment-1", "person-1", "pricing"))
service.drain(platform)
service.on_message(Message("m-event-1", "acme", "instagram", "person-1", "me@example.com"))
service.drain(platform)
