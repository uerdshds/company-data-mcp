# 部署到魔搭(ModelScope) MCP 托管 —— Gitee 路线

魔搭以 **stdio 启动命令 + 仓库** 的方式托管：平台拉取你的 Gitee 仓库，
用 `uvx` 安装并以 stdio 启动本服务，再统一包装成 `/<id>/mcp` 的 StreamableHTTP 端点。

## 一、把代码推到 Gitee（你来做）

1. 登录 Gitee → 新建仓库（**公开**），仓库名建议 `company-reconcile-mcp`，**不要**勾选自动初始化。
2. 回到本目录执行（把 URL 换成你的仓库地址）：
   ```bash
   cd E:/Desktop/code/MCP
   git remote add origin https://gitee.com/<你的用户名>/company-reconcile-mcp.git
   git push -u origin main
   ```
   （已配好 git 账号 `明人不放屁`；push 时按提示输 Gitee 账号密码 / 私人令牌）

## 二、在魔搭"创建 MCP 服务"里填启动命令

服务页面 → 部署/托管环节，类型选 **stdio**，启动命令填：

```
uvx --from git+https://gitee.com/<你的用户名>/company-reconcile-mcp.git company-reconcile-mcp
```

若表单是 command/args 分开的结构，则：
```json
{
  "command": "uvx",
  "args": ["--from", "git+https://gitee.com/<你的用户名>/company-reconcile-mcp.git", "company-reconcile-mcp"]
}
```

> 备选（若平台无 uvx，只有 pip）：
> `pip install git+https://gitee.com/<你的用户名>/company-reconcile-mcp.git && company-reconcile-mcp`

部署成功后，平台会给出端点：`https://mcp.api-inference.modelscope.net/<id>/mcp`
（你已有 id `9a8d78b7a7f649`）。

## 三、在钉钉 DEAP 接入

企业技能中心 → 自定义技能 → 新建 MCP 插件 → 类型 **StreamableHTTP** →
URL 填魔搭端点 `https://mcp.api-inference.modelscope.net/9a8d78b7a7f649/mcp` →
「插件检测」应拉到工具 `reconcile_company_tables` → 把技能加到智能体。

## 注意事项

- **首次冷启动较慢**：pandas/pdfplumber 等依赖在魔搭侧首次安装需要时间，属正常。
- **代码更新**：改完 `git push`，魔搭重新拉取即可（无需改启动命令）。
- **文件入参**：工具的 `file_a/file_b` 接钉盘可下载 URL 或路径，由智能体把上传文件地址传入。
- **传输已对齐**：`company-reconcile-mcp` 入口强制 stdio（见 `server.py: main_stdio`），符合魔搭托管契约。
