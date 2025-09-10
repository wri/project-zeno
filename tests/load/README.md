# Zeno Load Testing

This directory contains comprehensive load testing tools for the Project Zeno chat endpoint using [Locust](https://locust.io/).

## Setup

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Set machine user token:**
   ```bash
   export ZENO_MACHINE_USER_TOKEN="zeno-key_<prefix>_<secret>"
   ```

3. **Create a machine user (if needed):**
   ```bash
   python src/cli.py create-machine-user --name "Load Test Bot" --email "loadtest@test.com" --create-key --key-name "load-test"
   ```

## Quick Start

### Run Predefined Scenarios

```bash
# Smoke test (1 user, 2 minutes)
python tests/load/scenarios.py smoke

# Load test (10 users, 5 minutes)
python tests/load/scenarios.py load

# Stress test (50 users, 10 minutes)
python tests/load/scenarios.py stress

# Spike test (100 users, 3 minutes)
python tests/load/scenarios.py spike

# Run all scenarios sequentially
python tests/load/scenarios.py all
```

### Run with Web UI

```bash
# Start web UI for interactive testing
python tests/load/scenarios.py load --web-ui

# Then open http://localhost:8089 in your browser
```

### Custom Locust Commands

```bash
cd tests/load

# Basic load test
locust -f locustfile.py --host http://localhost:8000 --users 10 --spawn-rate 2 -t 5m --headless

# With web UI
locust -f locustfile.py --host http://localhost:8000

# Save results to CSV
locust -f locustfile.py --host http://localhost:8000 --users 20 --spawn-rate 4 -t 10m --headless --csv results

# Generate HTML report
locust -f locustfile.py --host http://localhost:8000 --users 20 --spawn-rate 4 -t 10m --headless --html report.html
```

## Test Scenarios

### User Behavior Patterns

The load tests simulate three types of user behavior:

1. **Quick Queries (30% of traffic)**
   - Simple geographic questions
   - Fast response expected
   - Examples: "Deforestation in Brazil", "Protected areas in Costa Rica"

2. **Analysis Queries (50% of traffic)**
   - Complex data analysis requests
   - Longer processing time expected
   - Examples: "Compare deforestation between Brazil and Indonesia 2020-2023"

3. **Conversations (20% of traffic)**
   - Multi-turn interactions using `thread_id`
   - 3-6 follow-up questions per conversation
   - Simulates real user exploration patterns

### Predefined Scenarios

| Scenario | Users | Duration | Purpose |
|----------|-------|----------|---------|
| **Smoke** | 1 | 2 min | Basic functionality validation |
| **Load** | 10 | 5 min | Normal usage simulation |
| **Stress** | 50 | 10 min | High load testing |
| **Spike** | 100 | 3 min | Traffic burst simulation |

## Configuration

### Environment Variables

```bash
# Required: Machine user API token
export ZENO_MACHINE_USER_TOKEN="zeno-key_<prefix>_<secret>"

# Optional: API base URL (default: http://localhost:8000)
export API_BASE_URL="https://api.zeno.example.com"
```

### Configuration Files

- **`config.py`**: Main configuration settings
- **`test_data.py`**: Query patterns and test data
- **`locustfile.py`**: Core Locust user behavior
- **`scenarios.py`**: Predefined scenario runner

## Monitoring and Metrics

### Built-in Metrics

Locust provides these metrics by default:
- Request rate (requests/second)
- Response times (min/max/avg/95th percentile)
- Failure rate
- Response size distribution

### Custom Metrics

The load tests also track:
- **Quota Usage**: Machine user daily quota consumption
- **Streaming Metrics**: Bytes and chunks received per request
- **Conversation Flow**: Thread continuity and turn counts

### Quota Monitoring

Machine users have a quota of 1000 requests/day. Monitor usage with:
```bash
# Check quota in response headers
curl -H "Authorization: Bearer $ZENO_MACHINE_USER_TOKEN" \\
     -X POST http://localhost:8000/api/chat \\
     -H "Content-Type: application/json" \\
     -d '{"query":"test"}' -I
```

Look for headers:
- `X-Prompts-Used`: Current usage count
- `X-Prompts-Quota`: Daily quota limit

## Example Usage

### 1. Basic Load Test

```bash
# Set up machine user token
export ZENO_MACHINE_USER_TOKEN="zeno-key_abc12345_def67890abcdef67890abcdef67890abcdef12"

# Run load test
python tests/load/scenarios.py load
```

### 2. Performance Monitoring

```bash
# Run stress test with detailed reporting
locust -f tests/load/locustfile.py \\
       --host http://localhost:8000 \\
       --users 50 --spawn-rate 5 -t 10m \\
       --headless --csv stress_results --html stress_report.html
```

### 3. Interactive Testing

```bash
# Start web UI for real-time monitoring
python tests/load/scenarios.py load --web-ui

# Open http://localhost:8089
# Adjust users and spawn rate dynamically
# Monitor real-time charts and statistics
```

## Interpreting Results

### Success Criteria

- **Response Time**: 95th percentile < 30 seconds for analysis queries
- **Failure Rate**: < 1% for all request types
- **Throughput**: System should handle target user load
- **Quota Usage**: Should not exceed machine user limits

### Common Issues

1. **Authentication Errors**: Check machine user token format
2. **Timeout Errors**: Increase timeout values in config
3. **Quota Exceeded**: Use multiple machine users or reduce load
4. **Streaming Failures**: Check network connectivity and timeout settings

### Performance Bottlenecks

Monitor these areas:
- **Database Connections**: PostgreSQL connection pool limits
- **LangGraph Processing**: AI model response times
- **API Rate Limits**: External data source throttling
- **Memory Usage**: Large streaming responses

## Advanced Usage

### Custom User Behavior

Create custom user classes in `locustfile.py`:

```python
class CustomTestUser(ZenoChatUser):
    wait_time = between(1, 3)

    @task(1)
    def custom_behavior(self):
        # Your custom test logic
        payload = {"query": "Custom test query"}
        self.make_chat_request(payload, "custom_test")
```

### Environment-Specific Testing

```bash
# Production-like testing
export API_BASE_URL="https://staging.zeno.example.com"
python tests/load/scenarios.py stress

# Local development
export API_BASE_URL="http://localhost:8000"
python tests/load/scenarios.py smoke
```

### Distributed Load Testing

Run Locust in distributed mode for higher load:

```bash
# Master node
locust -f locustfile.py --master --host http://localhost:8000

# Worker nodes (run on multiple machines)
locust -f locustfile.py --worker --master-host=<master-ip>
```

## Troubleshooting

### Common Errors

**"Configuration error: ZENO_MACHINE_USER_TOKEN must be set"**
- Set the environment variable with a valid machine user token

**"Invalid machine user token format"**
- Token must start with `zeno-key_` and have 3 parts separated by `_`

**"HTTP 401: Invalid machine user key"**
- Token may be expired, inactive, or incorrect
- Create a new machine user or rotate the key

**"HTTP 429: Too Many Requests"**
- You've exceeded the quota limit
- Wait for quota reset or use multiple machine users

### Performance Issues

- **Slow Response Times**: Check server resources and database performance
- **Memory Errors**: Reduce concurrent users or streaming timeout
- **Connection Errors**: Increase timeout values or check network connectivity

### Debug Mode

Enable detailed logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Integration with CI/CD

Add load tests to your pipeline:

```yaml
# .github/workflows/load-test.yml
- name: Run Load Tests
  run: |
    export ZENO_MACHINE_USER_TOKEN="${{ secrets.LOAD_TEST_TOKEN }}"
    python tests/load/scenarios.py smoke
```

Store machine user tokens as encrypted secrets in your CI/CD system.
