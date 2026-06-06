# 贡献指南

感谢你对 Hedera 项目的兴趣！

## 如何贡献

### 报告 Bug

1. 在 [Issues](https://github.com/Lustrum258/Hedera-agent-Local-AI-Personality-Engine/issues) 中搜索是否已有相同问题
2. 如果没有，创建一个新的 Issue，包含：
   - 问题描述
   - 复现步骤
   - 期望行为 vs 实际行为
   - 环境信息（Python 版本、操作系统）

### 提交代码

1. Fork 本仓库
2. 创建你的特性分支：`git checkout -b feature/my-feature`
3. 提交你的改动：`git commit -m 'Add some feature'`
4. 推送到分支：`git push origin feature/my-feature`
5. 创建一个 Pull Request

### 代码规范

- Python 3.10+ 兼容
- 遵循 PEP 8 风格
- 新功能请添加适当的注释
- 保持代码简洁，避免不必要的依赖

### 开发环境

```bash
git clone https://github.com/Lustrum258/Hedera-agent-Local-AI-Personality-Engine.git
cd Hedera-agent-Local-AI-Personality-Engine
pip install -e .
python -m hedera desktop
```

## 许可证

提交代码即表示你同意你的贡献以 [MIT 许可证](LICENSE) 发布。
