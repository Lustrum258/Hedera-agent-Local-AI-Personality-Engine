"""
AIGC检测插件 v3.1 — 训练脚本（修复版）
支持12维特征 + 对抗训练 + 真实感数据集生成

v3.1 变更：
  - 数据集生成全面升级：AI文本用真实论文模板 + 模型输出模拟
  - 加入对抗样本生成：同义替换、长句拆短、插入口语、改连接词
  - 加入混合样本（人写框架 + AI扩写 + 润色）
  - 支持 adversarial training 模式
  - 自动评估并打印特征重要性
  - 修复了编码问题，确保 stdout 正常输出

用法：
  1. 生成数据并训练：python train.py --generate --train
  2. 使用外部数据：python train.py --data 数据集.csv
  3. 完整对抗训练：python train.py --generate --train --adversarial
"""

import os
import sys
import argparse
import csv
import pickle
import random
import math
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from plugins.aigc_detector.main import extract_features


# ─── 对抗扰动函数 ───

def _synonym_replace(text, rate=0.05):
    replacements = {
        "提出": ["提出", "给出", "设计", "构建"],
        "采用": ["采用", "使用", "利用", "借助"],
        "基于": ["基于", "依据", "根据", "在……基础上"],
        "实验": ["实验", "试验", "测试"],
        "方法": ["方法", "方式", "方案", "途径"],
        "结果": ["结果", "成果", "结论", "发现"],
        "重要": ["重要", "关键", "核心", "主要"],
        "显著": ["显著", "明显", "突出", "优异"],
        "提升": ["提升", "提高", "增强", "改善"],
        "分析": ["分析", "研究", "探讨", "考察"],
    }
    words = list(replacements.keys())
    random.shuffle(words)
    result = text
    for w in words[:max(1, int(len(words) * rate * 5))]:
        if w in result:
            result = result.replace(w, random.choice(replacements[w]), 1)
    return result


def _split_long_sentences(text, max_len=50):
    sents = re.split(r'[。！？]', text)
    new_sents = []
    for s in sents:
        s = s.strip()
        if len(s) <= max_len:
            new_sents.append(s)
        else:
            split_points = [m.start() for m in re.finditer(r'[，；]', s)]
            if not split_points:
                new_sents.append(s)
            else:
                mid = len(s) // 2
                best = min(split_points, key=lambda x: abs(x - mid))
                new_sents.append(s[:best])
                new_sents.append(s[best+1:])
    return "。".join(new_sents) + "。"


def _insert_colloquial(text, rate=0.1):
    colloquial_inserts = [
        "说白了，", "其实吧，", "简单来说，", "换句话说，",
        "我觉得，", "让我意外的是，", "说实话，",
    ]
    sents = re.split(r'[。！？]', text)
    sents = [s for s in sents if len(s.strip()) > 5]
    if not sents:
        return text

    n_insert = max(1, int(len(sents) * rate))
    indices = random.sample(range(len(sents)), min(n_insert, len(sents)))
    for i in indices:
        insert = random.choice(colloquial_inserts)
        sents[i] = insert + sents[i]

    return "。".join(sents) + "。"


def _change_conjunctions(text, rate=0.3):
    conj_map = {
        "然而": ["然而", "但是", "不过", "可是"],
        "因此": ["因此", "所以", "故而", "于是"],
        "此外": ["此外", "另外", "除此之外", "同时"],
        "综上所述": ["综上所述", "综上", "总而言之", "总的来说"],
        "实验结果表明": ["实验结果表明", "实验结果显示", "实验数据表明", "实验说明"],
        "基于上述分析": ["基于上述分析", "基于以上分析", "基于此", "据此"],
    }
    result = text
    for old, options in conj_map.items():
        if old in result and random.random() < rate:
            result = result.replace(old, random.choice(options), 1)
    return result


def _generate_adversarial(text, label):
    versions = [(text, label)]
    aug_funcs = [
        (_synonym_replace, 0.05),
        (_split_long_sentences, 50),
        (_insert_colloquial, 0.1),
        (_change_conjunctions, 0.3),
    ]
    for func, param in aug_funcs:
        try:
            if param is not None:
                augmented = func(text, param)
            else:
                augmented = func(text)
            if augmented != text and len(augmented) >= 30:
                versions.append((augmented, label))
        except:
            pass
    return versions


# ─── 数据集生成 ───

def generate_dataset(count=600, include_adversarial=True):
    """
    生成高质量训练数据集。
    返回 (texts, labels)
    """
    random.seed(42)

    # AI 文本模板
    ai_templates = [
        "本文提出了一种基于{method}的{task}方法。该方法采用{architecture}作为骨干网络，"
        "并引入{mechanism}机制来增强特征表示能力。实验结果表明，该方法在{dataset}数据集上"
        "取得了{result}的性能，验证了方法的有效性。综上所述，本文的工作为{field}领域"
        "提供了新的思路，具有重要的{value}。",

        "针对传统方法在{problem}中存在的{issue}问题，本文提出了一种改进方案。"
        "该方案通过{approach}来克服上述局限，从而提升{metric}。实验结果显示，"
        "改进后的方法在{dataset}上取得了{result}。基于上述分析，本文的方法具有"
        "重要的{value}。",

        "本文的主要贡献包括三个方面。第一，提出了一种新颖的{method}框架，"
        "该框架融合了{technique1}和{technique2}的优势。第二，在{dataset}上"
        "进行了充分的实验验证。第三，分析了{scenario}场景下的应用效果。"
        "实验结果表明，该方法取得了优异的性能。",

        "与传统方法相比，本文提出的{method}方法具有明显的优势。传统方法在"
        "{problem}场景下存在{issue}的问题，而本文方法通过{approach}有效解决了"
        "这一瓶颈。在{dataset}上的实验结果表明，本文方法在{metric}上提升了"
        "{percent}。值得注意的是，该方法在{scenario}场景下表现尤为突出。",

        "本文提出了一种基于深度学习的{task}方法，旨在解决{problem}问题。"
        "该方法首先通过{approach}提取特征，然后利用{architecture}进行建模。"
        "在{dataset}数据集上的实验结果显示，本文方法在{metric}上达到了"
        "{result}的水平，显著优于现有方法。此外，消融实验验证了各个模块的"
        "有效性。研究结果表明，该方法具有重要的理论意义和实际应用价值。"
        "未来的工作将探索该方法在{scenario}场景下的扩展应用。",
    ]

    ai_vars = {
        "method": ["深度学习", "注意力机制", "多任务学习", "迁移学习", "强化学习",
                    "图神经网络", "自监督学习", "元学习", "联邦学习", "对比学习",
                    "知识蒸馏", "多模态融合", "生成对抗网络", "变分自编码器"],
        "task": ["图像识别", "自然语言处理", "目标检测", "语义分割", "文本分类",
                 "情感分析", "命名实体识别", "机器翻译", "语音识别", "推荐系统",
                 "问答系统", "图像生成", "异常检测", "时间序列预测"],
        "architecture": ["卷积神经网络", "Transformer", "BERT", "ResNet", "ViT",
                         "LSTM", "GraphSAGE", "GAN", "VAE", "U-Net"],
        "mechanism": ["注意力", "自注意力", "多尺度特征融合", "残差连接",
                      "门控机制", "图卷积", "特征金字塔", "通道注意力"],
        "dataset": ["公开数据集", "ImageNet", "COCO", "SQuAD", "GLUE",
                    "CIFAR-10", "CIFAR-100", "MNIST", "PubMed", "WN18RR",
                    "MS-COCO", "Cityscapes", "AG-News", "THUCNews"],
        "result": ["优异", "良好", "显著", "令人满意", "出色", "领先", "优越"],
        "value": ["理论意义", "实际应用价值", "参考价值", "研究意义", "推广价值",
                  "学术价值", "实践意义"],
        "field": ["计算机视觉", "自然语言处理", "数据挖掘", "人工智能",
                  "模式识别", "机器学习", "深度学习"],
        "problem": ["数据稀疏", "过拟合", "计算效率低", "泛化能力差", "标注成本高",
                    "类别不平衡", "长尾分布", "噪声干扰"],
        "issue": ["性能瓶颈", "鲁棒性不足", "可解释性差", "收敛速度慢",
                  "内存占用高", "训练不稳定"],
        "approach": ["引入注意力机制", "采用多尺度特征融合", "设计自适应损失函数",
                     "使用知识蒸馏技术", "构建端到端框架", "提出新的训练策略",
                     "设计轻量化网络结构", "引入对比学习范式"],
        "metric": ["准确率", "召回率", "F1分数", "AUC值", "收敛速度",
                   "推理速度", "参数量", "内存占用"],
        "percent": ["5%", "10%", "15%", "20%", "3.2%", "8.5%", "12.7%", "6.3%"],
        "scenario": ["实际应用", "工业部署", "移动端", "实时处理",
                     "跨域迁移", "小样本学习"],
        "technique1": ["卷积神经网络", "Transformer", "图神经网络", "生成对抗网络"],
        "technique2": ["注意力机制", "残差学习", "多任务学习", "元学习"],
    }

    # 人类文本模板（模拟真实写作风格）
    human_templates = [
        "我们做了{num}组实验来验证这个方法。第一组是在{dataset}上跑的，结果发现效果还{result}。"
        "后来又试了试{scenario}的情况，效果{result2}。说实话，这个结果有点{feeling}，本来以为会差一些。",

        "这个课题做了大概{time}。一开始我们用的是{method}，但效果不太理想。"
        "后来换成了{method2}，调整了几次参数之后才慢慢好起来。中间踩了不少坑，"
        "比如{problem}的问题就折腾了{time2}。",

        "我来说说这个实验的具体过程。首先把数据准备好，大概{num}条样本。"
        "然后跑了一遍{method}，结果发现{problem}。后来跟{person}讨论了一下，"
        "他建议试试{approach}，果然好了不少。不过还有一些细节没处理好，"
        "后续打算继续优化。",

        "这篇论文的动机其实很简单。我们在实际工作中发现{problem}的问题很突出，"
        "现有的方法又不太适用。所以就想自己搞一个方案试试。"
        "最开始的想法比较粗糙，后来改了好几版才定型。最后的实验结果还行，"
        "但跟理想状态还有差距。",

        "这个方法的思路是从{field}那边借鉴过来的。我们做了一些改进，"
        "主要是针对{problem}做了优化。实验跑了{num}轮，每次的结果不太一样，"
        "取平均之后效果还算可以。不过这个方法的局限性也很明显，"
        "比如在{scenario}场景下表现就不太好。后续打算从{approach}方向继续改进。",
    ]

    human_vars = {
        "num": ["三", "四", "五", "几", "多组", "若干"],
        "dataset": ["自己的数据集", "公开数据集", "实际采集的数据", "标准测试集"],
        "result": ["不错", "还行", "挺好的", "可以", "凑合"],
        "result2": ["也还行", "挺好的", "差不多", "稍微差一点", "出乎意料地好"],
        "scenario": ["实际场景", "真实环境", "工业应用", "移动端", "大规模数据"],
        "feeling": ["出乎意料", "意外", "有点意思", "让人欣慰", "挺惊喜的"],
        "time": ["大半年", "几个月", "半年多", "将近一年", "一段时间"],
        "method": ["传统方法", "基线方法", "已有的方案", "经典模型"],
        "method2": ["改进的版本", "新方案", "优化后的模型", "我们自己设计的"],
        "problem": ["过拟合", "数据不平衡", "收敛慢", "效果不稳定", "泛化差",
                    "训练时间长", "内存不够"],
        "time2": ["好几周", "一个多月", "挺长时间", "很久"],
        "person": ["师兄", "导师", "同事", "合作者", "朋友"],
        "approach": ["加正则化", "调学习率", "换损失函数", "改网络结构",
                     "增加数据", "做数据增强"],
        "field": ["NLP", "CV", "数据挖掘", "推荐系统", "语音识别"],
        "num_rounds": ["几十", "上百", "几十轮", "很多"],
    }

    # 生成 AI 文本
    ai_texts = []
    for _ in range(count // 2):
        template = random.choice(ai_templates)
        vars_dict = {}
        for key, values in ai_vars.items():
            vars_dict[key] = random.choice(values)

        try:
            text = template.format(**vars_dict)
        except KeyError:
            text = template
            for k, v in vars_dict.items():
                text = text.replace("{" + k + "}", str(v))
            text = re.sub(r'\{[^}]+\}', '某', text)

        if len(text) >= 30:
            ai_texts.append(text)

    # 生成人类文本
    human_texts = []
    for _ in range(count // 2):
        template = random.choice(human_templates)
        vars_dict = {}
        for key, values in human_vars.items():
            vars_dict[key] = random.choice(values)

        try:
            text = template.format(**vars_dict)
        except KeyError:
            text = template
            for k, v in vars_dict.items():
                text = text.replace("{" + k + "}", str(v))
            text = re.sub(r'\{[^}]+\}', '某', text)

        if len(text) >= 20:
            human_texts.append(text)

    # 构建数据集
    texts = ai_texts + human_texts
    labels = [1] * len(ai_texts) + [0] * len(human_texts)

    # 生成混合样本（人写开头 + AI扩写）
    mixed_count = count // 6
    for _ in range(mixed_count):
        if human_texts and ai_texts:
            h = random.choice(human_texts)
            a = random.choice(ai_texts)
            split_point = len(h) // 2
            mixed = h[:split_point] + "。" + a[len(a)//3:]
            if len(mixed) >= 40:
                texts.append(mixed)
                labels.append(1)  # 混写视为AI（含AI成分）

    # 加入对抗样本
    if include_adversarial:
        adv_texts = []
        adv_labels = []
        for t, l in zip(texts, labels):
            versions = _generate_adversarial(t, l)
            for vt, vl in versions:
                if vt != t:
                    adv_texts.append(vt)
                    adv_labels.append(vl)
        texts.extend(adv_texts)
        labels.extend(adv_labels)

    # 打乱
    combined = list(zip(texts, labels))
    random.shuffle(combined)
    texts, labels = zip(*combined) if combined else ([], [])

    print(f"生成数据集：{len(texts)} 条（AI: {sum(labels)} 条，人类: {len(labels)-sum(labels)} 条）")
    sys.stdout.flush()

    return list(texts), list(labels)


def load_csv_data(path):
    """从 CSV 加载外部数据"""
    texts, labels = [], []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            texts.append(row['text'])
            labels.append(int(row['label']))
    return texts, labels


# ─── 训练 ───

def train_xgboost(texts, labels, use_adversarial=False):
    """用 XGBoost 训练分类器"""
    try:
        import numpy as np
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
        from xgboost import XGBClassifier
    except ImportError as e:
        print(f"缺少依赖：{e}")
        print("请安装：pip install numpy scikit-learn xgboost")
        sys.exit(1)

    print("提取特征...")
    sys.stdout.flush()
    features_list = []
    valid_texts = []
    valid_labels = []

    for t, l in zip(texts, labels):
        try:
            feats = extract_features(t)
            if feats and all(isinstance(v, (int, float)) for v in feats.values()):
                features_list.append([feats[f"f{i}"] for i in range(1, 13)])
                valid_texts.append(t)
                valid_labels.append(l)
        except Exception as e:
            print(f"特征提取失败（跳过）：{str(e)[:50]}")
            continue

    X = np.array(features_list)
    y = np.array(valid_labels)

    print(f"有效样本：{X.shape[0]} 条，特征维度：{X.shape[1]}")

    if use_adversarial:
        print(f"对抗训练模式：{X.shape[0]} 条")
        sys.stdout.flush()

    # 划分训练/测试集
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print("训练 XGBoost...")
    sys.stdout.flush()

    model = XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        use_label_encoder=False,
        eval_metric='logloss',
    )
    model.fit(X_train, y_train)

    # 评估
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    print("\n" + "=" * 60)
    print("评估结果")
    print("=" * 60)
    print(classification_report(y_test, y_pred, target_names=["Human", "AI"]))

    cm = confusion_matrix(y_test, y_pred)
    print(f"混淆矩阵：")
    print(f"  TN={cm[0][0]}  FP={cm[0][1]}")
    print(f"  FN={cm[1][0]}  TP={cm[1][1]}")

    auc = roc_auc_score(y_test, y_proba)
    print(f"AUC: {auc:.4f}")

    # 特征重要性
    feature_names = [
        "字频分布熵", "句长变异系数", "字级MATTR", "四字格重复率",
        "学术套话熵", "文白混合度", "标点熵", "重复3-gram比率",
        "主语省略率", "连接词重复率", "语域波动", "风格断裂分",
    ]
    importance = model.feature_importances_
    sorted_idx = np.argsort(importance)[::-1]

    print("\n特征重要性：")
    for idx in sorted_idx:
        print(f"  f{idx+1} {feature_names[idx]}: {importance[idx]:.4f}")

    sys.stdout.flush()
    return model


def save_model(model):
    """保存模型到插件目录"""
    model_path = os.path.join(os.path.dirname(__file__), "classifier.pkl")
    with open(model_path, 'wb') as f:
        pickle.dump(model, f)
    print(f"\n模型已保存：{model_path}")


# ─── 主入口 ───

def main():
    parser = argparse.ArgumentParser(description="AIGC 检测训练脚本 v3.1")
    parser.add_argument("--generate", action="store_true", help="生成训练数据")
    parser.add_argument("--count", type=int, default=600, help="生成数据量")
    parser.add_argument("--data", type=str, help="外部数据 CSV 路径")
    parser.add_argument("--train", action="store_true", help="训练模型")
    parser.add_argument("--adversarial", action="store_true", help="使用对抗训练")
    args = parser.parse_args()

    texts, labels = [], []

    if args.generate:
        print("生成训练数据...")
        sys.stdout.flush()
        texts, labels = generate_dataset(count=args.count, include_adversarial=args.adversarial)
        # 保存生成的数据
        data_path = os.path.join(os.path.dirname(__file__), "training_data.csv")
        with open(data_path, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["text", "label"])
            for t, l in zip(texts, labels):
                writer.writerow([t, l])
        print(f"数据已保存：{data_path}")
        sys.stdout.flush()

    if args.data:
        ext_texts, ext_labels = load_csv_data(args.data)
        texts.extend(ext_texts)
        labels.extend(ext_labels)

    if args.train and texts and labels:
        model = train_xgboost(texts, labels, use_adversarial=args.adversarial)
        save_model(model)
    elif args.train:
        print("没有数据可用。使用 --generate 生成数据或 --data 指定外部数据。")


if __name__ == "__main__":
    main()
