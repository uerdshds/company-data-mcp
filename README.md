# 公司名对碰 MCP Server（钉钉 DEAP 自定义技能）

把两份表格（Excel / CSV / 电子版 PDF）按 **公司名称 + 日期** 做模糊对碰，
**AND 逻辑**：名称相似度达标 **且** 日期在容差内才算匹配。结果分三档：
`已匹配 / 待复核 / 未匹配`，每条带名称相似度分与日期相差天数。

## 目录结构

| 文件 | 作用 |
|------|------|
| `matcher.py` | 核心逻辑：读取 + 表头识别 + 公司名规范化 + rapidfuzz 匹配（与 MCP 解耦） |
| `server.py` | FastMCP 服务，StreamableHTTP 传输，端点 `/message` |
| `test_local.py` | 本地直接测核心逻辑（不经 MCP） |
| `test_client.py` | MCP 客户端连服务测试（模拟 DEAP 调用） |
| `samples/` | 示例数据（含全角/简称/日期格式/容差等噪声） |
| `deap-config.json` | DEAP「JSON 导入」用的配置 |

## 本地运行与自测

```bash
# 1. 装依赖（已建好 .venv）
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. 直接测核心逻辑
.venv/Scripts/python.exe test_local.py            # 默认 容差0
.venv/Scripts/python.exe test_local.py --tol 1    # 日期容差1天

# 3. 启动 MCP 服务
.venv/Scripts/python.exe server.py                # 监听 0.0.0.0:8000/message

# 4. 另开终端，用 MCP 客户端验证
.venv/Scripts/python.exe test_client.py
```

## 部署到魔搭(ModelScope) 托管

魔搭 MCP 托管底层是函数计算 FC，部署后给一个稳定 StreamableHTTP 端点：
`https://mcp.api-inference.modelscope.net/<id>/mcp`（本项目 id 已为 `9a8d78b7a7f649`）。

- 部署物：`Dockerfile` + `matcher.py` + `server.py` + `requirements.txt`。
- 镜像已设 `MCP_HTTP_PATH=/mcp`、`MCP_TRANSPORT=streamable-http`、端口读 `PORT`，与魔搭端点对齐。
- 若魔搭 FC 运行时要求 stdio 包装，把环境变量改成 `MCP_TRANSPORT=stdio` 即可。

> 本地+ngrok 仍可用作联调：`MCP_HTTP_PATH=/message ngrok http 8000`。

## 接入钉钉 DEAP

1. **拿到公网端点**：魔搭托管地址 `https://mcp.api-inference.modelscope.net/9a8d78b7a7f649/mcp`。

2. **注册自定义技能**：企业技能中心 → 自定义技能 → 新建 MCP 插件
   - **快速创建**：类型选 `StreamableHTTP`，HTTP URL 填上面的魔搭 `/mcp` 地址。
   - 或 **JSON 导入**：用 `deap-config.json`。
   - 点「插件检测」，应能拉到工具 `reconcile_company_tables`。

3. **把技能加到智能体**：智能体 → 技能 → 添加插件 → 选本技能。

4. **配置智能体提示词**，让模型在用户要"对碰/核对"两份表时调用本技能（见下）。

### 建议的智能体提示词片段
```
当用户提供两份文件并要求"对碰/核对/匹配"时，调用【公司名对碰】插件，
把两个文件地址传给 file_a / file_b；需要时设置 name_threshold(默认85)、
date_tolerance_days(默认0)。拿到 matched/to_review/unmatched 三档结果后，
用简洁中文汇总，并务必如实列出"待复核"条目，不得自行判定为匹配。
```

## 关键约束与说明

- **传输**：StreamableHTTP（DEAP 不支持 Stdio）。服务路径默认 `/mcp`，可用环境变量 `MCP_HTTP_PATH` 改；传输用 `MCP_TRANSPORT` 切 `stdio`。
- **文件入参**：`file_a`/`file_b` 支持「可下载 URL（钉盘链接）」或本地路径。DEAP 场景下，
  由智能体把用户上传文件的下载地址作为参数传入，本服务自行下载解析。
- **鉴权（可选）**：设 `MCP_API_KEY=xxx` 后，请求需带 Header `X-Api-Key: xxx`
  （在 DEAP 技能的「请求头」里加同名 Header）。系统还会自动注入
  `X-DingTalk-User-Id` / `X-DingTalk-User-Job-Number`。
- **PDF**：仅支持电子版（文字可选）；扫描件需先 OCR（项目里 `../agent-mcp-workflow/OCR.py` 可参考）。

## 可调参数

| 参数 | 默认 | 含义 |
|------|------|------|
| `name_threshold` | 85 | 公司名相似度阈值(0-100)，越高越严 |
| `date_tolerance_days` | 0 | 日期容差天数，0=必须同一天 |
| `strip_suffix` | false | 比对时剥离「有限公司」等组织形式后缀 |
| `name_col_* / date_col_*` | 自动 | 手动指定列名（留空则按表头别名自动识别） |
