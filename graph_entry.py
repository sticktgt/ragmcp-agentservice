from config import CONFIG
from chain_graph import build_agent_graph
from chain_graph import build_agent_graph_obj

def make_graph(config):
    return build_agent_graph_obj(CONFIG, rag_tool=None)
