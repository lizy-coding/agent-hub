# 单用户本机工作流控制面

Hub 管理流程声明、当前版本、队列、租约与历史；Forge 执行教学能力并展示结果。它与工程迁移/发布 Graph 分开，不调用模型、shell、Git 或发布接口。远端 Git 保存正式源码与决议，本机保存运行状态。

本轮只运行当前目录声明的版本，不维护旧执行版本、不提供旧库迁移或命令兼容层。历史运行仍冻结定义与输入；保留历史不等于可以重放旧实现。

## 统一入口

在 Agent Hub 根目录执行：

    ./agent workflow serve
    ./agent workflow inspect
    ./agent workflow maintain
    ./agent maintenance-test --profile workflow

默认状态为 $XDG_STATE_HOME/agent-hub/workflows-v2.sqlite3；未配置时为 ~/.local/state/agent-hub/workflows-v2.sqlite3。可用 --state 指定。令牌默认位于状态库同目录 workflows.token，以 0600 独占创建，正常退出删除；现有令牌不覆盖。数据库和备份同样为 0600，运行文件不进入 Git。

服务仅监听 127.0.0.1:8768，可用 --port 改端口，不能开启远端监听。Web 连接需 --allow-origin 明确允许开发来源。Forge 页面填写该地址与当前令牌，连接只在本页面保留；其他设备上的回环地址不会连接这台机器。没有后台 executor、多租户或远端运行服务。

当前 Hub 主机为 macOS/POSIX。serve 与离线 maintain 对同一状态路径持有进程锁，拒绝第二个写服务；服务运行时可 inspect，但先停止服务再执行离线 maintain。启动先取得端口，再启用声明，绑定失败不会意外升级状态库。进程锁文件保留在库旁，退出释放锁，不依赖删除文件来解锁。

旧示例 /tmp/forge-workflows.sqlite3 不自动导入。旧库被明确拒绝，原文件保持原样；新状态格式为 2，HTTP/流程声明仍采用 forge.workflow.v1。旧 python -m ...server 启动方式停止使用，统一采用 ./agent workflow。

## 声明与更新

默认声明源为 src/agent_hub/learning_workflows/catalog.json：schema、能力列表、当前流程、步骤、输入规则和表格列。--catalog 可指定另一个明确的本地 JSON；不扫描目录、不下载远端模板、不执行声明中的代码。

当前是 articles.explore v1，两步为请求教学文章、筛选整理，数据均为合成教学数据。只支持有界整数、字符串、布尔输入和有界表格输出。未知字段/能力、无界规则、重复步骤和同流程多个当前版本均拒绝；输入校验从声明生成，不在 Python 重复维护五个字段。

1. 在所属 Git 仓库修改声明或实现，定向验证，再按任务授权提交/推送。定义变更必须增加版本号，相同 id/version 不可覆盖。
2. 准备匹配的 Forge 执行端。Hub 只接受当前能力清单，不建设多版本兼容矩阵。
3. 停止旧 Hub，以新声明启动。Hub 在同一写事务中安装声明、结算旧任务、清除旧租约和执行端注册，再启用当前目录。目录的 SHA256 是此次启用身份。
4. 未完成旧任务结算为 cancelled，错误与事件明确标记“升级终止”；原定义、输入、事件与已终态历史保留。迟到旧回报拒绝。
5. Forge 用新令牌重新连接注册。未启用版本的新建请求拒绝。回滚也要准备对应实现，不改写历史。

重复启用相同目录不会中断任务；非法目录或同版本内容冲突整体回滚。自定义目录每次启动须使用同一 --catalog 配置。inspect/maintain 不加载默认目录，更不会意外回滚当前版本。

## 重试与执行边界

普通新建可省略 workflowVersion，采用当前启用版；显式指定旧版冲突。带 retryOf 的请求采用当前版，仍校验工作流身份、目标执行端注册、原运行终态和当前输入。单用户允许重新连接后的新执行端重试旧身份的任务，不建设租户隔离模型。新运行有独立 ID，关联旧运行并冻结新定义；不合法输入明确拒绝，不猜测迁移。

相同 executorId/requestKey 的相同请求返回原运行；升级不会把网络重传变成新版重试。真正重试必须使用新 requestKey。eventKey 内容幂等，步骤顺序、结果大小和终态均校验。租约 45 秒，队列 120 秒，读取/调度及维护时结算过期。

控制面终止不等于外部动作已撤销。Forge 当前轮询到 cancelled 会取消本地执行；真实进程停止和业务副作用需要独立联调证据。Forge 页面和文章 runner 仍固定支持文章 v1，本轮未修改 Forge；启用其他版本前须更新消费者，Hub fixture 通过不代表跨项目升级验收。

## 保留、备份与恢复

服务启动维护一次，运行期间每分钟检查。终态从 finishedAt 起保留 30 天，关联删除输入、结果、错误和事件；活动任务先按超时规则结算，不能静默当作历史删除。模型会话默认不落盘，显式保存的脱敏证据独立管理。

每天最多自动产生一次 SQLite 一致性快照，保存在 <state>.backups/backup-000.sqlite3 等固定槽位，默认轮换 7 份。只有写入和检查成功才记录成功时间；服务内错误从 /v1/status 查询，命令失败返回 2。--retention-days 和 --backup-count 可配置。

    ./agent workflow maintain --force-backup
    ./agent workflow restore --source /明确路径/backup-000.sqlite3 --state /新的不存在路径/restored.sqlite3
    ./agent workflow inspect --state /新的不存在路径/restored.sqlite3

inspect 以 SQLite 只读模式打开，不创建库、不结算过期。restore 不覆盖已有目标；先校验快照，终止未完成任务、清除执行端与租约，应用保留策略，再原子安装新文件，防止恢复后重放旧任务。原库和快照不修改。

滚动备份可能暂存主库已过期的内容，恢复前再次清理；不承诺第 30 天所有副本都物理删除。服务关闭时没有后台维护进程，需要外部本机调度调用 maintain；本轮没有安装系统调度或重启用户服务。离线每日调度需要主机配置验收。

## HTTP 接口

所有接口使用临时 Bearer 令牌，Web 来源单独校验。GET 运行会结算过期；无写入审计使用 CLI inspect。

| 接口 | 用途 |
| --- | --- |
| GET /v1/workflows | 当前流程、能力、catalogDigest；不列出旧版可执行项 |
| GET /v1/status | 目录摘要、维护/备份时间、维护错误 |
| POST /v1/executors | 注册当前能力清单 |
| POST /v1/runs | 新建或关联最新版重试 |
| GET /v1/runs?executorId=... | 最近 30 条记录 |
| GET /v1/runs/{id} | 冻结定义、输入、状态、finishedAt、结果和事件 |
| POST /v1/executors/{id}/claim | 原子领取，一次一个任务，返回独立租约 |
| POST /v1/runs/{id}/events | 按租约和幂等键回传有序事件 |
| POST /v1/runs/{id}/cancel | 排队直接取消，执行中等待确认 |

没有 HTTP 编辑/发布声明、shell 命令、任意 URL、模型代码或制品发布接口。

## 验证边界

workflow fixture 使用临时数据库和随机回环端口，覆盖真实 CLI 启停、HTTP 鉴权、升级/领取并发、旧租约拒绝、最新版重试、事务回滚、清理、备份故障、恢复和旧库拒绝，不访问用户运行库或远端模型。

Forge 的 integration_test/workflow_ecosystem_test.dart 是独立跨项目验收，需要显式连接测试服务。本轮 Hub 测试不代表该联调、页面视觉、后台执行或跨设备验收通过。
