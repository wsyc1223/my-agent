"""
测试 astream_events 在 resume 场景下是否支持 on_chat_model_stream 事件。
用法: 先把 graph.py 末尾的 async for 两行删掉，然后运行此脚本。
"""
import asyncio
import uuid
from src.graph import app

async def main():
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # 第一步：发送会触发工具调用的消息，让它中断在 tools 前
    state_input = {
        "messages": [{"role": "user", "content": "北京今天天气怎么样？"}],
        "tool_call_count": 0,
    }
    print("=== 第一步: 初始 invoke (会触发工具调用，被 interrupt 中断) ===")
    result = await app.ainvoke(state_input, config)
    print(f"最后一条消息类型: {result['messages'][-1].type}")
    print(f"是否有 tool_calls: {bool(result['messages'][-1].tool_calls)}")

    state = app.get_state(config)
    print(f"next: {state.next}")

    # 第二步：resume 并监听 astream_events
    from langgraph.types import Command

    print("\n=== 第二步: resume (approved=True) 观察 astream_events 事件类型 ===")
    events_seen = set()

    try:
        async for event in app.astream_events(
            Command(resume="continue"),
            config,
            version="v2",
        ):
            event_type = event["event"]
            events_seen.add(event_type)

            if event_type == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                if chunk.content:
                    print(f"  [TOKEN] '{chunk.content}'")

            elif event_type == "on_chat_model_start":
                print(f"  [LLM START]")

            elif event_type == "on_chat_model_end":
                print(f"  [LLM END]")

            elif event_type == "on_tool_start":
                print(f"  [TOOL START] {event.get('name', '')}")

            elif event_type == "on_tool_end":
                print(f"  [TOOL END] {event.get('name', '')}")

            elif event_type == "on_chain_stream":
                print(f"  [CHAIN STREAM]")

            # 不打印全部事件细节，避免输出过多
    except Exception as e:
        print(f"\n!!! 报错: {type(e).__name__}: {e}")

    print(f"\n=== 观察到的事件类型 ===")
    for t in sorted(events_seen):
        print(f"  - {t}")

if __name__ == "__main__":
    asyncio.run(main())
