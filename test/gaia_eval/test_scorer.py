import sys
from pathlib import Path

import pytest

# 确保可以找到 gaia_eval 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gaia_eval.scorer import GaiaScorer



class TestNormalizeText:
    """文本标准化测试"""

    def test_basic(self):
        assert GaiaScorer.normalize_text("  Hello World  ") == "hello world"

    def test_remove_articles(self):
        assert GaiaScorer.normalize_text("The quick brown fox") == "quick brown fox"
        assert GaiaScorer.normalize_text("a cat") == "cat"
        assert GaiaScorer.normalize_text("an apple") == "apple"

    def test_remove_punctuation(self):
        assert GaiaScorer.normalize_text("Hello, World!") == "hello world"
        assert GaiaScorer.normalize_text("Dr. Smith's") == "dr smiths"

    def test_collapse_whitespace(self):
        assert GaiaScorer.normalize_text("hello   world") == "hello world"


class TestNormalizeNumber:
    """数字标准化测试"""

    def test_remove_commas(self):
        assert GaiaScorer.normalize_number("1,000") == "1000"
        assert GaiaScorer.normalize_number("1,234,567") == "1234567"

    def test_remove_trailing_zeros(self):
        assert GaiaScorer.normalize_number("3.0") == "3"
        assert GaiaScorer.normalize_number("100.00") == "100"

    def test_keep_decimals(self):
        assert GaiaScorer.normalize_number("3.14") == "3.14"

    def test_currency(self):
        assert GaiaScorer.normalize_number("$100") == "100"
        assert GaiaScorer.normalize_number("€50") == "50"

    def test_percentage(self):
        assert GaiaScorer.normalize_number("75%") == "75"

    def test_non_number(self):
        assert GaiaScorer.normalize_number("hello") == "hello"


class TestScore:
    """评分逻辑测试"""

    def test_exact_match(self):
        assert GaiaScorer.score("Paris", "Paris") is True

    def test_case_insensitive(self):
        assert GaiaScorer.score("paris", "Paris") is True
        assert GaiaScorer.score("PARIS", "paris") is True

    def test_with_articles(self):
        assert GaiaScorer.score("The Eiffel Tower", "Eiffel Tower") is True

    def test_number_match(self):
        assert GaiaScorer.score("1,000", "1000") is True
        assert GaiaScorer.score("3.0", "3") is True
        assert GaiaScorer.score("$100", "100") is True

    def test_list_match(self):
        assert GaiaScorer.score("a, b, c", "c, b, a") is True
        assert GaiaScorer.score("Apple, Banana", "Banana, Apple") is True

    def test_list_mismatch(self):
        assert GaiaScorer.score("a, b", "a, b, c") is False

    def test_mismatch(self):
        assert GaiaScorer.score("London", "Paris") is False

    def test_empty_prediction(self):
        assert GaiaScorer.score("", "Paris") is False

    def test_empty_gold(self):
        assert GaiaScorer.score("Paris", "") is False

    def test_both_empty(self):
        assert GaiaScorer.score("", "") is False

    def test_whitespace_handling(self):
        assert GaiaScorer.score("  Paris  ", "Paris") is True

    def test_number_with_text(self):
        # 混合的数字和文本不应该触发数字匹配
        assert GaiaScorer.score("42 years", "42") is False

    def test_floating_point(self):
        assert GaiaScorer.score("3.14", "3.14") is True
        assert GaiaScorer.score("3.14", "3.15") is False
