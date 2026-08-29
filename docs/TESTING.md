# 测试指南

[English](./TESTING-EN.md) | 中文文档

MiroFish 的自动化测试分为两套：后端 pytest 与前端 Vitest。两者都可以在**不配置任何
API 密钥、不启动任何服务**的前提下直接运行。

## 一分钟上手

在项目根目录执行：

```bash
npm test
```

这条命令会依次跑完后端与前端的全部用例，约 30 秒。输出末尾的 `passed` 数字即为通过
的用例总数；只要没有 `failed`，就说明一切正常。

想看覆盖率：

```bash
npm run test:coverage
```

### 前置要求

| 工具 | 用途 | 检查方式 |
|------|------|---------|
| **uv** | 运行后端测试 | `uv --version` |
| **Node.js 18+** | 运行前端测试 | `node -v` |

后端测试**不需要**先执行 `npm run setup:backend`。`npm run test:backend` 会依据
`backend/requirements-test.txt` 自建一个临时环境，只装测试真正用到的轻量依赖
（首次约 20 秒，之后走 uv 缓存）。这样做是有意为之：完整的后端环境包含
`camel-oasis` / `camel-ai`，会连带装上 torch、transformers 等数 GB 的包，而这些
只有真正跑模拟的子进程才需要。

前端测试需要先安装依赖（`npm run setup` 或 `cd frontend && npm install`）。

## 全部命令

| 命令 | 作用 |
|------|------|
| `npm test` | 跑完后端 + 前端全部用例 |
| `npm run test:backend` | 仅后端（pytest） |
| `npm run test:frontend` | 仅前端（Vitest） |
| `npm run test:frontend:watch` | 前端监听模式，改完代码自动重跑 |
| `npm run test:coverage` | 两端都跑，并输出覆盖率报告 |
| `npm run test:backend:coverage` | 仅后端覆盖率 |
| `npm run test:frontend:coverage` | 仅前端覆盖率 |

也可以在各自目录里直接调用，便于只跑某个文件：

```bash
# 后端：只跑一个文件 / 一个用例
cd backend
uv run --no-project --with-requirements requirements-test.txt pytest tests/test_retry.py
uv run --no-project --with-requirements requirements-test.txt pytest -k "traversal"

# 前端：只跑一个文件
cd frontend
npx vitest run tests/api-retry.test.js
```

## 覆盖率报告在哪里

跑完 `npm run test:coverage` 后：

- **后端**：终端会打印逐文件的明细；HTML 报告在 `backend/htmlcov/index.html`
- **前端**：终端会打印汇总；HTML 报告在 `frontend/coverage/index.html`
  （另有 `lcov.info`，可供 IDE 插件或 Codecov 之类的服务读取）

用浏览器打开 HTML 报告，可以逐行查看哪些代码没有被测试覆盖。

## 覆盖了什么，没覆盖什么

这一点值得说清楚，否则光看"30%"这个数字容易产生误解。

**已被充分覆盖（90% 以上）** —— 纯逻辑、不依赖外部服务的部分：

| 模块 | 覆盖内容 |
|------|---------|
| `app/utils/safe_path.py` | 路径穿越防护：`../` 类标识符不得逃出存储根目录 |
| `app/utils/json_repair.py` | 修复 LLM 返回的残缺 JSON（`<think>` 标签、markdown 围栏等） |
| `app/utils/retry.py` | 指数退避的同步 / 异步两个版本，含抖动上限 |
| `app/utils/zep_paging.py` | Zep 图谱 cursor 分页的全部终止条件 |
| `app/utils/file_parser.py` | 文本分块、编码探测回退（UTF-8 → GBK → 兜底） |
| `app/models/project.py` | 项目落盘 / 读取的往返一致性 |
| `app/models/task.py` | 任务状态机与并发安全的单例 |
| 前端 `src/api/`、`src/store/` | 每个接口的 URL、方法、查询参数；重试策略；响应信封拆包 |

此外 `backend/tests/test_api_contract.py` 会**遍历整张路由表**做契约测试：任何接口
都必须返回 `{success: ...}` 信封、不得在关闭 DEBUG 时回传堆栈、不得因为未知 ID
或畸形请求体返回 500。新增路由的当天就会自动被这组用例覆盖，无需另外补测试。

**未被覆盖** —— 需要真实外部服务才能执行的部分：

- `app/services/report_agent.py`、`ontology_generator.py`、`graph_builder.py`：
  需要可用的 LLM API
- `app/services/zep_*.py`：需要 Zep Cloud 账号与图谱数据
- `app/services/simulation_runner.py`、`oasis_profile_generator.py`：
  需要 OASIS 模拟环境（以及大量 LLM 调用）
- 前端 `.vue` 视图：目前依赖人工验收

这些模块占了代码量的大头，所以**整体覆盖率约 30%，但这 30% 覆盖的是几乎全部
可离线验证的逻辑**。要把剩下的部分纳入自动化测试，需要先给外部服务引入一层可替换
的适配层，这是一项独立的重构工作。

## 覆盖率门槛

两端都设了**防回退门槛**（不是目标值）：低于门槛测试会失败，用于发现"测试被误删或
被跳过"这类问题。

| 位置 | 门槛 | 当前实测 |
|------|------|---------|
| `backend/pyproject.toml` → `[tool.coverage.report] fail_under` | 29% | 约 30%（含分支覆盖） |
| `frontend/vite.config.js` → `test.coverage.thresholds` | 语句/函数/行 90%，分支 85% | 约 99% |

补充测试把覆盖率提上去之后，请**同步上调这两处门槛**，让它始终紧贴当前水平。

## 编写新测试

### 后端

用例放在 `backend/tests/`，文件名以 `test_` 开头。`conftest.py` 提供三个 fixture：

| Fixture | 作用 |
|---------|------|
| `isolated_storage` | 把所有持久化根目录指向临时目录，测试不会写到 `backend/uploads/` |
| `app` | 一个 `TESTING=True` 的 Flask 应用（自动带上 `isolated_storage`） |
| `client` | 该应用的测试客户端，可直接 `client.get('/api/...')` |

```python
def test_creating_a_project_returns_its_id(client):
    response = client.post('/api/graph/ontology/generate', json={})
    assert response.status_code < 500
    assert response.get_json()['success'] is False
```

异步用例加 `@pytest.mark.asyncio`（`asyncio_mode` 已设为 `strict`）。

**注意**：测试中不要真的去 sleep。用 `monkeypatch` 把 `time.sleep` /
`asyncio.sleep` 换掉并记录调用参数，既能断言退避时长，又能让整套用例在 20 秒内跑完
——现有的 `test_retry.py` 与 `test_zep_paging.py` 都是这么做的。

### 前端

用例放在 `frontend/tests/`，文件名以 `.test.js` 结尾（与组件同目录的 `src/**/*.test.js`
也会被拾取）。`tests/setup.js` 会在每个用例
前把 `console.error` / `console.warn` 换成 spy，这样刻意触发失败路径的用例不会在
通过时刷屏打印堆栈；需要断言日志内容时，直接读 `console.error.mock.calls` 即可。

## 持续集成

`.github/workflows/test.yml` 会在每个 Pull Request、以及推送到 `main` 时运行：

- **Backend (pytest)** —— 与本地 `npm run test:backend` 完全相同的依赖与命令，
  并额外产出覆盖率报告
- **Frontend (vitest + build)** —— 跑测试、检查覆盖率门槛，再执行一次生产构建

两个 job 的覆盖率 HTML 报告都会作为 artifact 上传，可在 Actions 页面下载。

## 常见问题

**`uv: command not found`**
后端测试需要 uv。安装方式见 [uv 官方文档](https://docs.astral.sh/uv/)，或执行
`curl -LsSf https://astral.sh/uv/install.sh | sh`。

**前端报 `Cannot find module 'vitest'`**
前端依赖没装。执行 `npm run setup`，或 `cd frontend && npm install`。

**后端测试报大量 `ModuleNotFoundError`**
多半是绕开 `npm run test:backend`、直接用系统 Python 跑了 pytest。请使用上文给出的
`uv run --no-project --with-requirements requirements-test.txt pytest` 命令。

**测试会不会动到我的真实数据？**
不会。`isolated_storage` fixture 把所有存储根目录重定向到临时目录，测试结束即销毁；
`conftest.py` 也会为 `LLM_API_KEY` / `ZEP_API_KEY` 填入占位值，测试不会发出任何真实
的外部 API 请求。
