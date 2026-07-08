# Taskiq Redis 评测系统联调试验

这是一个专用于测试 Taskiq 与 Redis 异步评估管线的测试文档。
当我们通过 API 接口上传这个文件后，主后端应该首先接收该文件并开启后台线程进行分块解析与向量化入库。
后台分块落库完成后，主服务应当向 Redis 队列发送一个 trace_id，触发 Taskiq Worker 异步消费，利用 Ragas 进行 Faithfulness、Answer Relevance 评估，并回传分数到 Langfuse 平台。