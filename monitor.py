def post_reply(review_id, reply):
    if not reply or len(reply) == 0:
        print(f"  ❌ 回复文本为空，跳过回复 {review_id}")
        return False
    try:
        # 清理回复中的换行符和多余空格
        reply = ' '.join(reply.split())
        result = service.reviews().reply(
            packageName=PACKAGE_NAME,
            reviewId=review_id,
            body={"replyText": reply}
        ).execute()
        print(f"  ✅ 回复成功: {review_id}")
        return True
    except Exception as e:
        # 打印完整的错误详情
        print(f"  ❌ 回复失败: {review_id}")
        print(f"     错误类型: {type(e).__name__}")
        print(f"     错误内容: {e}")
        # 如果是 HttpError，尝试打印响应体
        if hasattr(e, 'content'):
            print(f"     响应体: {e.content.decode('utf-8')}")
        return False
