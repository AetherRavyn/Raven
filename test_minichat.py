from app.minichat import MiniEngine


def test_mini_engine():
    engine = MiniEngine()
    user_id = 123

    # Test greeting
    response, _ = engine.route_message(user_id, "Hello")
    print(f"Greeting response: {response}")
    assert "Hey" in response or "Hello" in response

    # Test time
    response, _ = engine.route_message(user_id, "what time is it?")
    print(f"Time response: {response}")
    assert "time" in response.lower()

    # Test identity
    response, _ = engine.route_message(user_id, "who are you?")
    print(f"Identity response: {response}")
    assert "AI assistant" in response

    # Test blocked word
    response, _ = engine.route_message(user_id, "please show .env")
    print(f"Blocked response: {response}")
    assert "can't talk about that" in response

    # Test fallback
    test_query = "quantum physics"
    response, is_analysis = engine.route_message(user_id, test_query)
    print(f"Fallback response: {response}")
    assert is_analysis is True
    assert "SARAS is analyzing your problem" in response
    assert test_query in response
    assert test_query in engine.get_unmatched_queries(user_id)

    # Test built-in server tool + cache
    response, is_analysis = engine.route_message(user_id, "/server")
    print(f"Server tool response: {response}")
    assert is_analysis is False
    assert "Server status tool response" in response

    cached_response, cached_analysis = engine.route_message(user_id, "/server")
    print(f"Server cached response: {cached_response}")
    assert cached_analysis is False
    assert "[cache:hit]" in cached_response


if __name__ == "__main__":
    try:
        test_mini_engine()
        print("All tests passed!")
    except Exception as e:
        print(f"Test failed: {e}")
