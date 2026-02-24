"""GAIA 答案评分模块

实现 GAIA 官方的 quasi exact match 评分逻辑。
参考: https://huggingface.co/spaces/gaia-benchmark/leaderboard
"""

import re
import string


class GaiaScorer:
    """GAIA 准精确匹配评分器"""

    @staticmethod
    def normalize_text(text: str) -> str:
        """文本标准化

        - 去除首尾空白
        - 统一为小写
        - 移除冠词 (a, an, the)
        - 移除标点
        - 合并连续空白
        """
        text = text.strip().lower()

        # 移除冠词
        text = re.sub(r"\b(a|an|the)\b", " ", text)

        # 移除标点
        text = text.translate(str.maketrans("", "", string.punctuation))

        # 合并连续空白
        text = re.sub(r"\s+", " ", text).strip()

        return text

    @staticmethod
    def normalize_number(text: str) -> str:
        """数字标准化

        - "1,000" → "1000"
        - "3.0" → "3"
        - "$100" → "100"
        - "100%" → "100"
        """
        # 去除货币符号
        text = re.sub(r"[$€£¥]", "", text)
        # 去除百分号
        text = text.rstrip("%")
        # 去除千分位逗号
        text = text.replace(",", "")

        # 判断是否为数字，若是则标准化
        try:
            num = float(text)
            # 如果是整数则去掉 .0
            if num == int(num):
                return str(int(num))
            return str(num)
        except ValueError:
            return text

    @classmethod
    def score(cls, prediction: str, gold: str) -> bool:
        """计算单条评估的准精确匹配分数

        Args:
            prediction: 模型预测答案
            gold: 黄金标准答案

        Returns:
            True 表示匹配，False 表示不匹配
        """
        if not prediction or not gold:
            return False

        # 先尝试数字比较
        pred_num = cls.normalize_number(prediction.strip())
        gold_num = cls.normalize_number(gold.strip())
        try:
            if float(pred_num) == float(gold_num):
                return True
        except ValueError:
            pass

        # 检查是否为列表答案（逗号分隔）
        if "," in gold:
            pred_items = sorted(cls.normalize_text(item) for item in prediction.split(","))
            gold_items = sorted(cls.normalize_text(item) for item in gold.split(","))
            if pred_items == gold_items:
                return True

        # 文本标准化比较
        pred_normalized = cls.normalize_text(prediction)
        gold_normalized = cls.normalize_text(gold)

        return pred_normalized == gold_normalized
