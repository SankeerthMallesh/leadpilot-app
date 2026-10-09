from app.markdown_lite import render


def test_html_is_escaped():
    out = str(render('<script>alert(1)</script> <img src=x onerror=alert(1)>'))
    assert "<script>" not in out and "<img" not in out
    assert "&lt;script&gt;" in out


def test_bold_code_and_paragraphs():
    out = str(render("Use **bold** and `code`.\n\nSecond paragraph."))
    assert "<strong>bold</strong>" in out and "<code" in out and out.count("<p>") == 2


def test_bullet_and_numbered_lists():
    assert "<ul" in str(render("- one\n- two")) and str(render("- one\n- two")).count("<li>") == 2
    assert "<ol" in str(render("1. first\n2. second"))


def test_empty_input_is_safe():
    assert "<p>" in str(render(""))
