from langchain.chains import GraphCypherQAChain
from langchain_community.graphs import Neo4jGraph
from langchain.prompts.prompt import PromptTemplate
from langchain_core.messages import SystemMessage
from langchain_core.messages import HumanMessage
from langchain_community.chat_models import BedrockChat
from retry import retry
from timeit import default_timer as timer
import streamlit as st
import ingestion.bedrock_util as bedrock_util
from langchain_community.embeddings import BedrockEmbeddings
from neo4j_driver import run_query
from json import loads, dumps

bedrock = bedrock_util.get_client()

model_name = st.secrets["SUMMARY_MODEL"]
if model_name == '':
    model_name = 'anthropic.claude-v2'


SYSTEM_PROMPT = """You are a Financial expert with SEC filings who can answer questions only based on the context below.
* Think step by step before answering.
* Do not return helpful or extra text or apologies
* Just return summary to the user. DO NOT start with Here is a summary
* List the results in rich text format (no HTML) if there are more than one results
* Summarise the results from the context in accordance to what the user asks and quote available references
"""

PROMPT_TEMPLATE = """
<question>
{input}
</question>

Here is the context:
<context>
{context}
</context>
"""
PROMPT = PromptTemplate(
    input_variables=["input","context"], template=PROMPT_TEMPLATE
)

EMBEDDING_MODEL = BedrockEmbeddings(model_id="amazon.titan-embed-text-v1", client=bedrock)
def vector_graph_qa(query):
    query_vector = EMBEDDING_MODEL.embed_query(query)
    return run_query("""
    CALL db.index.vector.queryNodes('document-embeddings', 50, $queryVector)
    YIELD node AS doc, score
    OPTIONAL MATCH (doc)<-[:HAS]-(company:Company), (company)<-[:OWNS]-(manager:Manager)
    RETURN company.nameOfIssuer AS companyName, doc.text as text, manager.name as asset_manager, avg(score) AS score
    ORDER BY score DESC LIMIT 50
    """, params =  {'queryVector': query_vector})

def df_to_context(df):
    result = df.to_json(orient="records")
    parsed = loads(result)
    return dumps(parsed)

@retry(tries=5, delay=5)
def get_results(question):
    start = timer()
    try:
        bedrock_llm = BedrockChat(
            model_id=model_name,
            client=bedrock,
            model_kwargs = {
                "temperature":0,
                "top_k":1, "top_p":0.1,
                "anthropic_version":"bedrock-2023-05-31",
                "max_tokens": 50000
            }
        )
        df = vector_graph_qa(question)
        ctx = df_to_context(df)
        ans = PROMPT.format(input=question, context=ctx)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=ans
            )
        ]
        result = bedrock_llm(messages).content
        r = {}
        r['context'] = ans
        r['result'] = result
        return r
    finally:
        print('Cypher Generation Time : {}'.format(timer() - start))


