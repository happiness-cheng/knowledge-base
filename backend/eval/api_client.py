"""实际 Agent 评测的每题请求限额；不修改应用常规客户端。"""

from time import perf_counter
import json


def filter_tool_context(name, raw, allowed_node_ids):
    """只允许选定知识节点进入模型；保留真实检索结果顺序，不替换检索算法。"""
    data = json.loads(raw)
    if name == 'search_knowledge_base' and isinstance(data, list):
        data = [item for item in data if item.get('node_id') in allowed_node_ids]
    elif name == 'get_node_details' and isinstance(data, dict):
        if data.get('id') not in allowed_node_ids:
            data = {'error': 'node outside authorized evaluation scope'}
        else:
            data['relationships'] = [item for item in data.get('relationships', [])
                                     if item.get('other_node_id') in allowed_node_ids]
    else:
        data = {'error': 'tool disabled in authorized evaluation'}
    return json.dumps(data, ensure_ascii=False)


class RequestBudgetExceeded(RuntimeError):
    pass


class BoundedAIClient:
    def __init__(self, sdk, model, *, max_requests=3, max_output_tokens=1024):
        if not 1 <= max_requests <= 3 or not 1 <= max_output_tokens <= 1024:
            raise ValueError('evaluation limits exceed authorized profile')
        self.sdk, self.model = sdk, model
        self.max_requests, self.max_output_tokens = max_requests, max_output_tokens
        self.calls = []
        self.budget_exceeded = False

    def _request(self, **kwargs):
        if len(self.calls) >= self.max_requests:
            self.budget_exceeded = True
            raise RequestBudgetExceeded('evaluation request budget exceeded')
        kwargs['max_tokens'] = min(kwargs.get('max_tokens', self.max_output_tokens), self.max_output_tokens)
        row = {'attempt': len(self.calls) + 1, 'status': 'started'}
        self.calls.append(row)
        start = perf_counter()
        try:
            response = self.sdk.messages.create(model=self.model, **kwargs)
            usage = getattr(response, 'usage', None)
            row.update(status='returned', input_tokens=getattr(usage, 'input_tokens', None),
                output_tokens=getattr(usage, 'output_tokens', None),
                cache_creation_input_tokens=getattr(usage, 'cache_creation_input_tokens', 0) or 0,
                cache_read_input_tokens=getattr(usage, 'cache_read_input_tokens', 0) or 0)
            return response
        except Exception as exc:
            row.update(status='error', error_type=type(exc).__name__)
            raise
        finally:
            row['latency_ms'] = round((perf_counter() - start) * 1000, 3)

    def chat_with_tools(self, **kwargs):
        return self._request(**kwargs)

    def chat(self, **kwargs):
        response = self._request(**kwargs)
        return '\n'.join(block.text for block in response.content if block.type == 'text')

    @property
    def usage_totals(self):
        if not self.calls or any(row['status'] != 'returned' or row.get('input_tokens') is None
                                 or row.get('output_tokens') is None for row in self.calls):
            return None
        return {'input_tokens': sum(row['input_tokens'] + row['cache_creation_input_tokens']
                                    + row['cache_read_input_tokens'] for row in self.calls),
                'output_tokens': sum(row['output_tokens'] for row in self.calls)}
