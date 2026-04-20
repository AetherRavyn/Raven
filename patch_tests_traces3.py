with open("test_orchestrator_filetool.py", "r") as f:
    content = f.read()

target1 = """        self.assertIn(
            "[tool:stubkillofail action:chat_completion_resilient status:error]",
            text,
        )"""

replacement1 = """        self.assertTrue(any("[tool:stubkillofail action:chat_completion_resilient status:error]" in line for line in botsignal._annotation_lines(payload)))"""

target2 = """        self.assertIn(
            "[tool:stubkillo action:chat_completion_resilient status:ok]", text
        )"""

replacement2 = """        self.assertTrue(any("[tool:stubkillo action:chat_completion_resilient status:ok]" in line for line in botsignal._annotation_lines(payload)))"""

content = content.replace(target1, replacement1)
content = content.replace(target2, replacement2)

with open("test_orchestrator_filetool.py", "w") as f:
    f.write(content)
