"""The code-based critic (agents/checks.py)."""
from podcast_agent.agents.checks import check_segment, word_script, words

HI = "अर्जुन, ये UPI payments असल में काम कैसे करते हैं?"


def issues(text, lang="hi", code_mix="medium", budget=None, history=()):
    return check_segment([("ARJUN", text, "")], [], lang, code_mix, budget or len(text), list(history))


def test_words_and_scripts():
    assert words(HI)[0] == "अर्जुन" and word_script("payments") == "Latin"


def test_a_good_line_passes():
    assert issues(HI) == []  # 2 of 10 words English = 20%, inside medium


def test_digits_and_symbols():
    iss = issues("यह 2016 में शुरू हुआ और 50% लोग payments करते हैं")
    assert any("digits" in i for i in iss) and any("symbol" in i for i in iss), iss


def test_code_mix_and_script():
    assert any("English" in i for i in issues("यह बहुत अच्छा है और सबके लिए सरल है"))
    # romanized Hindi is called out as a script problem
    assert any("Devanagari script" in i for i in issues("Wahi toh mystery hai, aaj hum samjhenge"))
    iss = issues("Kerala side-ல rush ஆகும் winds coastal areas-ல பயங்கர மழை", lang="ta")  # English-heavy, not romanized
    assert any("are English" in i for i in iss) and not any("romanized" in i for i in iss), iss
    assert any("wrong script" in i for i in issues("வணக்கம் நண்பர்களே இது payments பற்றி", code_mix="heavy"))


def test_repeats_length_and_stock_openers():
    t = "अच्छा तो UPI payments ऐसे काम करता है"
    assert any("too often" in i for i in issues(t, history=[("PRIYA", "अच्छा तो फिर क्या हुआ", "")] * 3))
    assert any("characters" in i for i in issues(t, budget=10 * len(t)))
    assert any("stock phrase" in i for i in issues("Exactly, that is how it works", lang="en"))


def test_fillers_and_cut_ins():
    ok = [("PRIYA", "So the bank checks the—", ""), ("ARJUN", "हम्म", "backchannel"), ("PRIYA", "and then it pays", ""),
          ("ARJUN", "Wait, who pays?", "cut")]
    assert not any("must come right after" in i for i in check_segment(ok, [], "en", "medium", 60, [])), ok
    iss = check_segment([("ARJUN", "first line", "cut"), ("PRIYA", "ok", ""), ("PRIYA", "me again", "backchannel"),
                         ("ARJUN", "hmm right yes sure okay", "backchannel")], [], "en", "medium", 50, [])
    assert sum("must come right after" in i for i in iss) == 2 and any("word or two" in i for i in iss), iss
    assert not any("stock phrase" in i for i in check_segment([("PRIYA", "a line", ""), ("ARJUN", "Exactly", "backchannel")],
                                                             [], "en", "medium", 15, []))
