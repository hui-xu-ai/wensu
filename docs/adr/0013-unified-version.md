# ADR 0013 · 四个发行物共用一个版本号

- 状态：accepted
- 日期：2026-11-09
- 取代：无（此前从未写下版本策略）
- 关联：ADR 0003（原生消息桥）、ADR 0012（桥的威胁模型）

## 背景

项目发行四样东西：PyPI 上的 `wensu` Python 包、浏览器扩展、native host、以及 npm 上的
DSH bundle。到 0.12.9 为止它们各自演进：

| 发行物 | 当时版本 |
|---|---|
| Python 包 / native host | 0.12.9 |
| 浏览器扩展 | 0.5.0 |
| DSH bundle | 0.4.4 |

每一条都能自圆其说：扩展只动过两次、bundle 只改一行配置，强行跟着 Python 包升号会让版本号
虚增。**但合起来产生了一个更糟的后果**：使用者手里三个数字对不上，而「这个组合能不能用」
在任何地方都查不到。装完 bundle 看见 0.4.5、`pip show wensu` 看见 0.12.10、扩展详情页写着
0.5.0——只能来问人。

版本号的职责是**让人判断配套关系**。做不到这一点，它就只是构建系统的内部记账。

## 决策

**四个发行物共用一个版本号。**

发版时五处必须一致，由 `scripts/check-versions.py` 校验并接入 CI（`ci.yml` 的
"Versions agree" 步骤）：

- `pyproject.toml` → `version`
- `src/scholar_search/__init__.py` → `__version__`
- `extension/manifest.json` → `version`
- `packages/dsh-wensu/package.json` → `version`
- `NOTICE` → `Version:`

从 0.12.10 起生效。npm 上更早的 `0.4.x` 保留可装，不再演进。

## 备选

### 备选 A：保持三套独立版本号，补一份兼容性矩阵

即当前的做法。被否决的原因很直接：矩阵需要人维护，而它维护得再好，使用者在装之前
也不会去读它；**版本号本身是唯一会被看见的兼容性声明**。

### 备选 B：只统一 Python 包与扩展，bundle 独立

bundle 确实不含检索代码，与 Python 包没有代码级耦合，只通过「PATH 上有个 `wensu`」相连。
被否决：这留下了最容易出错的一处——**装了 bundle 却没有配套的 `wensu`**，
是两个数字不一致里代价最高的那种。

### 备选 C：统一版本号，但只到次版本（如都写 0.12.x）

被否决：包管理器需要精确版本才能解析依赖，`0.12.x` 不是一个可以发布的版本号。

## 后果

- **代价**：每次发版要同时动四处版本号，即使扩展和 bundle 没有改动。多了几步机械操作，
  换来的是「数字相同即配套」这条可以一眼判断的规则。
- **缓解**：`scripts/check-versions.py` 把机械性交给 CI，漏改会直接红，不会发出去。
- **兼容性仍由三份契约定义**，版本号只回答「是不是一套」：桥协议版本（`PROTOCOL_VERSION`，
  双侧强制校验）、能力与渠道（`manifest.capabilities`，不支持即报错）、bundle 与 `wensu`
  （同号即配套）。详见 `docs/compatibility.md`。
- **`wensu status` 增加 `version` 与 `bridge_protocol`**，让接入方在启动时就能把
  「工具缺失」「工具是旧版」区分开——这两种情况的处理完全不同。
