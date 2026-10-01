from typing import Dict, List
from datetime import datetime

from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

G_COMPLIANCE_INDEX_NAME = "compliance-etl"

def pretty_response(response):
    if len(response["hits"]["hits"]) == 0:
        print("Your search returned no results.")
    else:
        for idx, hit in enumerate(response["hits"]["hits"], start=1):
            id = hit["_id"]
            score = hit["_score"]
            ref_code = hit["_source"].get("ref_code", None)
            title = hit["_source"].get("title", None)
            slug = hit["_source"].get("slug", None)
            parent_slug = hit["_source"].get("parent_slug", None)
            category = hit["_source"].get("category", None)
            description = hit["_source"].get("description", None)
            purpose = hit["_source"].get("purpose", None)
            guidance = hit["_source"].get("guidance", None)
            other_information = hit["_source"].get("other_information", None)
            means_of_verifiction = hit["_source"].get("means_of_verifiction", None)
            attributes = hit["_source"].get("attributes", None)
            references = hit["_source"].get("references", None)
            citers = hit["_source"].get("citers", None)
            #pretty_output = f"\nID: {id}\nPublication date: {publication_date}\nTitle: {title}\nSummary: {summary}\nRank: {idx}\nScore: {score}"
            pretty_output = f"\nID: {id}\nRank: {idx}\nScore: {score}\ntitle: '{title}'\ncategory: '{category}'\ndescription: '{description}'\npurpose: '{purpose}'\nguidance: '{guidance}'\nother_information: '{other_information}'\n"
            print(pretty_output)

def index_exists(es_client):
    return es_client.indices.exists(index=G_COMPLIANCE_INDEX_NAME)

def create_index(es_client):
    resp = es_client.indices.create(
        index=G_COMPLIANCE_INDEX_NAME,
        settings={
            #"analysis": {
            #    "analyzer": {
            #        "my_english_analyzer": {
            #            "type": "standard",
            #            "stopwords": "_english_"
            #        }
            #    }
            #},
            "analysis": {
                "filter": {
                    "english_stop": {
                        "type": "stop",
                        "stopwords": "_english_"
                    }
                },
                "analyzer": {
                    "my_english_analyzer": {
                        "type": "custom",
                        "tokenizer": "standard", # use the standard tokenizer, also already handles punctuation removal
                        "filter": [ "lowercase", "english_stop", "porter_stem" ] # filter out stopwords, lowercase tokens, and apply the porter stemmer
                    }
                }
            }
        },
        mappings={
            "properties": {
                "title": {
                    "type": "text",
                    "analyzer": "my_english_analyzer"
                },
                "description": {
                    "type": "text",
                    "analyzer": "my_english_analyzer"
                },
                "description_embedding": {
                    "type": "dense_vector",
                    "dims": 384,
                    "index": True,
                    "similarity": "cosine"
                }
            }
        },
        #ignore=[400] # resource_already_exists_exception
    )
    return resp

def refresh_index(es_client):
    # refresh elastic search index
    es_client.indices.refresh(index=G_COMPLIANCE_INDEX_NAME, ignore=[404])

def get_index_mapping(es_client):
    # gets the types of each field of the documents for the given index 
    return es_client.indices.get_mapping(index=G_COMPLIANCE_INDEX_NAME)

def insert_document(es_client, control: Dict, catalog: Dict):
    # NOTE: description embedding for hybrid retrieval
    control["description_embedding"] = model.encode(control["description"]).tolist()

    # add catalog identifiers to the control struct to allow identifying its document origin
    control["catalog_uuid"] = catalog["uuid"]
    control["catalog_name"] = catalog["metadata"]["name"]
    print(control["catalog_uuid"], control["catalog_name"])

    return es_client.index(index=G_COMPLIANCE_INDEX_NAME, id=control["slug"], document=control)

def update_document(es_client, control: Dict):
    # update a document, certain fields may be omitted to remain untouched at the index (an index insert operation with a document missing fields removes such fields)
    return es_client.update(index="test-index", id=control["slug"], document=control)

def empty_index(es_client):
    es_client.delete_by_query(index=G_COMPLIANCE_INDEX_NAME, body={ "query": { "match_all": {} } })

def delete_index(es_client):
    es_client.indices.delete(index=G_COMPLIANCE_INDEX_NAME, ignore=[404])

def search_index(es_client, max_size=10):
    return es_client.search(index=G_COMPLIANCE_INDEX_NAME, query={ "match_all": {} }, size=max_size)

def search_document_by_description(es_client, query: str, max_size=10):
    return es_client.search(index=G_COMPLIANCE_INDEX_NAME, query={ "match": { "description": query } }, size=max_size)

def search_document_by_all_fields(es_client, query: str, max_size=10):
    # NOTE: "query_string" can be used in the place of "match_all" to allow for operands like AND and OR in the query (note that bracket parameters differ)
    return es_client.search(index=G_COMPLIANCE_INDEX_NAME, query={ "multi_match": { "query": query, "fields": ["title", "description"] } }, size=max_size)# "fields": ["title", "description"]

def test_knn_search_by_description(es_client, query: str, max_size=10):
    query_vector = model.encode(query).tolist()

    return es_client.search(
        index=G_COMPLIANCE_INDEX_NAME,
        knn={
            "field": "description_embedding",
            "query_vector": query_vector,
            "k": 5,
            "num_candidates": 10,
        },
        size=max_size,
    )

def get_document(es_client, control: Dict):
    # get a document by its index id
    return es_client.get(index=G_COMPLIANCE_INDEX_NAME, id=control["slug"])


from collections import defaultdict
# https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion
# https://gist.github.com/srcecde/eec6c5dda268f9a58473e1c14735c7bb
def reciprocal_rank_fusion(*list_of_list_ranks_system, K=60):
    """
    Fuse rank from multiple IR systems using Reciprocal Rank Fusion.
    
    Args:
    * list_of_list_ranks_system: Ranked results from different IR system.
    K (int): A constant used in the RRF formula (default is 60).
    
    Returns:
    Tuple of list of sorted documents by score and sorted documents
    """
    # Dictionary to store RRF mapping
    rrf_map = defaultdict(float)

    # Calculate RRF score for each result in each list
    for rank_list in list_of_list_ranks_system:
        for rank, item in enumerate(rank_list[0], start=1):
            rrf_map[item] += 1 * rank_list[1] / (rank + K)

    # Sort items based on their RRF scores in descending order
    sorted_items = sorted(rrf_map.items(), key=lambda x: x[1], reverse=True)

    # Return tuple of list of sorted documents by score and sorted documents
    return sorted_items, [item for item, score in sorted_items]


def index_data(es_client, cdm_instances: Dict):
    global G_COMPLIANCE_INDEX_NAME

    refresh_index(es_client)

    #delete_index(es_client)
    #refresh_index(es_client)

    if not index_exists(es_client):
        create_index(es_client)
        #refresh_index(es_client)

    for control in cdm_instances["controls_list"]:
        resp = insert_document(es_client, control.model_dump(), cdm_instances["catalog"].model_dump())
        #print(resp)

    refresh_index(es_client)

    '''result = es_client.indices.analyze(
        index=G_COMPLIANCE_INDEX_NAME,
        analyzer="my_english_analyzer",
        text="The running dogs jumped quickly"
    )
    print(result)
    return'''

    #############################
    # search test
    query = "How can I be compliant with backup requirements in my organization?"
    sparse_retrieval = search_document_by_description(es_client, query)
    dense_retrieval = test_knn_search_by_description(es_client, query)
    #pretty_response(sparse_retrieval)
    #pretty_response(dense_retrieval)
    sparse_retrieval_docs = [doc["_source"]["slug"] for doc in sparse_retrieval["hits"]["hits"] if "slug" in doc["_source"].keys()]
    dense_retrieval_docs = [doc["_source"]["slug"] for doc in dense_retrieval["hits"]["hits"] if "slug" in doc["_source"].keys()]
    #print("Sparse retrieval docs:", sparse_retrieval_docs)
    #print("Dense retrieval docs:", dense_retrieval_docs)
    print(sparse_retrieval)
    print(dense_retrieval)

    # Combine the lists using RRF
    combined_list = reciprocal_rank_fusion((sparse_retrieval_docs, 0.5), (dense_retrieval_docs, 1.0))
    print(combined_list)
    print("Top 5 rrf documents:", combined_list[1][:5])
