# 第 7 轮 (round 7) · 地图臂答案（覆盖率优先配置，用户批准的 ≤45% 预算）

> 全文臂（Arm F）沿用第 5 轮答案：`../round5/ARMS.md` 的 "Arm F"。依据：本轮只改 `index.json` 的生成，`page.md` 未变（9 636 tok 不变）。
> 地图：`index.json` 17 211 B = **4 302 tok = 44.6%**；53 条 numbers（带原句）、36 条 key_sentences；逐字回查 100% 命中。

## Arm M（`map10/meta.json` + `map10/index.json`）

1. 膜反应器普遍存在 H₂ 浓差极化（concentration polarization），阻碍 H₂ 分离、抑制反应高效进行；催化剂床孔隙率分布同时决定流道与反应强度，优化分布可在不增加催化剂量前提下定向强化输运；多孔床输运阻力正是限制分离与反应的根源。〔1. Introduction；2. Model description；4. Conclusions〕
2. 变量 = 孔隙率场（Find: φ field）；目标 max obj = α η_CH4 + (1−α) ψ_H2；约束 ∭Ω φ dΩ ⩾ ∭Ω φ0 dΩ（式 26），用 COMSOL 解多物理场。〔2.3. Topology optimization method〕
3. φ0 = 0.5 就是 SMMR 原本的孔隙率；作为平均孔隙率下界约束是为避免为提升性能而增加催化剂用量（avoid increasing catalyst amount）。〔3.1. Topology optimization results〕
4. 前端均匀高孔隙率，中后段大量倾斜径向孔隙通道（inclined radial paths），与反应器轴线夹角 58.86°；演化后期（Iter > 40）转为"多条径向通道 + 梯度分布"混合模式，实现径向双向输运。机制：径向输运强化是反应-分离协同的本征机制（Fig. 5b 单向 / 5c 双向）。〔4. Conclusions；3.1；Highlights；Fig. 5〕
5. 主算例（φi = 0.5）：转化与分离性能分别相对提升 19.4% 与 26.4%；全文最大口径为 CH4 转化率与 H2 回收率最多提升 30.9% 与 35.9%。〔3.1. Topology optimization results；Highlights〕
6. 与 Tong et al.、Adris et al. 两组实验对比（Fig. 3a/3b）；具体偏差数值 地图未覆盖。〔2.4；Fig. 3〕
7. 网格达 69840-grids 后结果相对变化约 10⁻⁴。〔2.4. Model validation〕
8. Fig. 4b：不同初始 φi 场下目标与约束均趋稳，说明在 2.2.2 节设定下优化收敛、结果趋稳；配合 Fig. 4a 对多种初始均匀 φi 场做敏感性分析以逼近全局最优。〔3.1；Fig. 4〕
9. 控制目标权重 α 考察演化方向：仅以氢回收为目标（α = 0）时分布倾向径向梯度分布（radial gradient distribution）；对应分离性能 15.5%、甲烷转化率仅 2.9%（另有甲烷转化提升 24.0%，其 α 地图未标明）；整体提升随工况由 28.9%/42.8%/32.0% 降至 10.4%/22.9%/21.4%。〔3.3；Fig. 8〕
10. （1）原始转化 0.6 时甲烷转化率、燃料效率、氢回收率分别提升 28.9%、42.8%、32.0%，达理想性能（0.83）的 92.3%；（2）给定长度下整体性能提升 30.9–59.0%；（3）最大 CH4 转化率与 H2 回收率分别提升 30.9% 与 35.9%。〔4. Conclusions；Highlights〕

FILES_READ: `map10/meta.json`、`map10/index.json`
COVERAGE_GAPS: Q6（验证偏差数值）、Q7（未列逐套网格变化）、Q8（收敛结论句被省略号截断）、Q9（其它 α 的形貌与 24.0% 所属 α 未标）、Q4（Table 2 各值无指标名，未采信）。
