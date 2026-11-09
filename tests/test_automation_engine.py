import unittest

from automation_engine import AutomationService, Comment, Message


class FakePlatform:
    def __init__(self): self.calls = []
    def reply_to_comment(self, **kwargs): self.calls.append(("reply", kwargs))
    def send_dm(self, **kwargs): self.calls.append(("dm", kwargs))


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.service = AutomationService.open()
        self.service.create_automation(automation_id="a1", workspace_id="w1", keyword="pricing",
            reply_text="Sent you a DM!", prompt_text="What is your email?", link_text="https://go.example/link")
        self.platform = FakePlatform()

    def test_happy_path(self):
        self.assertTrue(self.service.on_comment(Comment("e1", "w1", "instagram", "c1", "u1", "pricing")))
        self.service.drain(self.platform)
        self.assertEqual([x[0] for x in self.platform.calls], ["reply", "dm"])
        self.assertTrue(self.service.on_message(Message("e2", "w1", "instagram", "u1", "email is jane@example.com")))
        self.service.drain(self.platform)
        self.assertEqual(self.platform.calls[-1][1]["text"], "https://go.example/link")
        run = self.service.db.execute("SELECT status, context_json FROM workflow_runs").fetchone()
        self.assertEqual(run["status"], "completed")
        self.assertIn("jane@example.com", run["context_json"])

    def test_duplicate_webhook_is_a_noop(self):
        comment = Comment("same", "w1", "instagram", "c1", "u1", "pricing")
        self.assertTrue(self.service.on_comment(comment))
        self.assertFalse(self.service.on_comment(comment))
        self.assertEqual(self.service.db.execute("SELECT count(*) FROM workflow_runs").fetchone()[0], 1)

    def test_non_email_message_keeps_waiting(self):
        self.service.on_comment(Comment("e1", "w1", "instagram", "c1", "u1", "pricing"))
        self.service.on_message(Message("e2", "w1", "instagram", "u1", "hello"))
        self.assertEqual(self.service.db.execute("SELECT status FROM workflow_runs").fetchone()[0], "waiting_for_email")


if __name__ == "__main__":
    unittest.main()
