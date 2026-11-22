# 第 4 轮验收 · 全文 vs 文献地图（10 问）

> 论文：Tang et al., *Synergistic enhancement of reaction and separation for a solar membrane reactor by
> topology optimization of catalyst bed*, Chem. Eng. J. 2023, DOI 10.1016/j.cej.2023.145123
> 产物：`work/tools/out/map9/`（page2md 0.3.0-m1，HEAD `133b5cf`）
> 判据（plan.md §7 M2）：答案一致率 **≥9/10**，且 conflict = 0；地图侧输入 **≤ 全文 35%**。

## 1. 两臂（严格隔离，各自独立子代理，互不可见）

| 臂 | 允许读 | 禁止读 | 输入体积 |
|---|---|---|---|
| **F 全文** | 仅 `map9/page.md` | index.json / brief / sections/* | 14 617 tok |
| **M 地图** | 仅 `map9/meta.json` + `map9/index.json` | page.md / brief / sections/* | 4 696 tok（meta 321 + index 4 375）= **32.1%** |

体积度量直接用 `tools/page2md.py::_estimate_tokens`（英文 ≈4 字符/token）实测，两侧同一把尺。
参考：`page.brief.md` 单独 2 254 tok（15.4%）；meta+index+brief 会到 47.5%，**超预算**，故本轮 M 臂不含 brief。

## 2. 10 个问题（两边一字不差）

1. 这篇论文要解决 SMMR（太阳能膜反应器）的什么问题？为什么催化剂床的孔隙率**分布**值得优化？
2. 拓扑优化用的是哪种方法（变量、目标函数、约束分别是什么）？
3. 为什么取初始孔隙率 φ0 = 0.5，并把它作为平均孔隙率的**下界**约束？
4. 最优拓扑的孔隙率分布在径向/轴向上是什么样？性能提升的物理机制是什么？
5. 优化后 CH4 转化率与 H2 回收率各提升多少？给出具体数值。
6. 模型验证与哪两组数据对比？偏差多少？
7. 网格无关性验证用了多少网格，相对变化多少？
8. Fig. 4 的收敛曲线说明了什么？
9. 在不同目标/权重下，拓扑演化方向有什么差别？
10. 结论里给出的主要定量结论（≥3 条，带具体数值）。

## 3. 评分（判官，独立子代理，可读全文）

逐题给出 `agree` / `partial` / `conflict` / `disagree`，并额外核查：

- **伪值**：M 答案里的数字必须能在 `page.md` 逐字找到，找不到即记 `fabricated`；
- **错值**：F 与 M 数字不同且 M 与原文一致 → 记 `F-err`（说明全文臂自身失误，不算地图缺陷）；
- **图注/公式**：涉及 Fig. 4、Eq. 编号的答案必须与原句比对。

`conflict` 专指两臂答案**互相矛盾且都被原文支持**（说明题面歧义），为 0 才合格。
