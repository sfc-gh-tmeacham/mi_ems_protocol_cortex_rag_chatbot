# First add the following packages:
# snowflake
# snowflake-ml-python
# snowflake-snowpark-python

import streamlit as st
# import time
from snowflake.core import Root 
from snowflake.cortex import Complete
from snowflake.snowpark.context import get_active_session

st.set_page_config(layout="wide")

session = get_active_session()
root = Root(session)

MODELS = [
    "snowflake-llama-3.3-70b",
    "claude-3-5-sonnet",
    "llama3.1-70b",
    "llama3.1-405b",
    "mistral-large2"
]

def init_messages():
    """
    Initialize the session state for chat messages. If the session state indicates that the
    conversation should be cleared or if the "messages" key is not in the session state,
    initialize it as an empty list.
    """
    if st.session_state.clear_conversation or "messages" not in st.session_state:
        st.session_state.messages = [{"role":"assistant","content":  """👋 Hi there! I'm your friendly AI assistant. Whether you have questions about the [State of Michigan EMS Protocol Suite](https://www.michigan.gov/mdhhs/inside-mdhhs/legislationpolicy/ems/protocols/michigan-protocols) or need guidance on specific procedures, I'm here to help. Just ask me anything!"""}]


def init_service_metadata():
    """
    Initialize the session state for cortex search service metadata. Query the available
    cortex search services from the Snowflake session and store their names and search
    columns in the session state.
    """
    if "service_metadata" not in st.session_state:
        services = session.sql("SHOW CORTEX SEARCH SERVICES;").collect()
        service_metadata = []
        if services:
            # TODO: remove loop once changes land to add the column metadata in SHOW
            for s in services:
                svc_name = s["name"]
                svc_search_col = session.sql(
                    f"DESC CORTEX SEARCH SERVICE {svc_name};"
                ).collect()[0]["search_column"]
                service_metadata.append(
                    {"name": svc_name, "search_column": svc_search_col}
                )

        st.session_state.service_metadata = service_metadata


def init_config_options():
    """
    Initialize the configuration options in the Streamlit sidebar. Allow the user to select
    a cortex search service, clear the conversation, toggle debug mode, and toggle the use of
    chat history. Also provide advanced options to select a model, the number of context chunks,
    and the number of chat messages to use in the chat history.
    """


    st.sidebar.button("Start New Conversation ✨", key="clear_conversation", type="primary", use_container_width=True)
    st.sidebar.toggle("Use chat history", key="use_chat_history", value=True)
    with st.sidebar.expander("Example Questions"):
        example_questions = {
            "Emergency Protocols": "Is it okay to remove a helmet?",
            "Procedure Guidelines": "Can an ambulance be canceled if the patient has a valid DNR order and experiences cardiac or respiratory arrest during transport?",
            "Elder Care": "What do I need to do if I suspect a senior citizen is being neglected?",
            "Response Coordination": "Can an ambulance be canceled after a request?",
            "Pediatric Care": "How should nausea be treated for a child?",
            "Legal Compliance": "What do I do if law enforcement wants me to draw blood and the subject refuses?",
            "Medical Resources": "What is MEDDRUN and CHEMPACK?",
            "Historical Reference": "Who was Hippocrates?",
            "Out of Scope Question": "What days do we have off this year?"
        }
        
        for question in example_questions.values():
            st.code(question, line_numbers=False, wrap_lines=True, language=None)

    with st.sidebar.expander(label="Advanced Options"):
        st.selectbox(
            "Select cortex search service:",
            [s["name"] for s in st.session_state.service_metadata],
            key="selected_cortex_search_service",
        )
        st.selectbox("Select model:", MODELS, key="model_name")
        st.toggle("Debug", key="debug", value=False)
        st.number_input(
            "Select number of context chunks",
            value=10,
            key="num_retrieved_chunks",
            min_value=1,
            max_value=10,
        )
        st.number_input(
            "Select number of messages to use in chat history",
            value=5,
            key="num_chat_messages",
            min_value=1,
            max_value=10,
        )

    #st.sidebar.expander("Session State").write(st.session_state)


def query_cortex_search_service(query):
    """
    Query the selected cortex search service with the given query and retrieve context documents.
    Display the retrieved context documents in the sidebar if debug mode is enabled. Return the
    context documents as a string.

    Args:
        query (str): The query to search the cortex search service with.

    Returns:
        str: The concatenated string of context documents.
    """
    db, schema = session.get_current_database(), session.get_current_schema()

    cortex_search_service = (
        root.databases[db]
        .schemas[schema]
        .cortex_search_services[st.session_state.selected_cortex_search_service]
    )

    context_documents = cortex_search_service.search(
        query, columns=[], limit=st.session_state.num_retrieved_chunks
    )
    results = context_documents.results

    service_metadata = st.session_state.service_metadata
    search_col = [s["search_column"] for s in service_metadata
                    if s["name"] == st.session_state.selected_cortex_search_service][0]

    context_str = ""
    for i, r in enumerate(results):
        context_str += f"{r[search_col]} \n" + "\n"

    if st.session_state.debug:
        st.sidebar.text_area("Context documents", context_str, height=500)

    return context_str
    
def get_chat_history():
    """
    Retrieve the chat history from the session state limited to the number of messages specified
    by the user in the sidebar options.

    Returns:
        list: The list of chat messages from the session state.
    """
    start_index = max(
        0, len(st.session_state.messages) - st.session_state.num_chat_messages
    )
    return st.session_state.messages[start_index : len(st.session_state.messages) - 1]

def complete(model, prompt):
    """
    Generate a completion for the given prompt using the specified model.

    Args:
        model (str): The name of the model to use for completion.
        prompt (str): The prompt to generate a completion for.

    Returns:
        str: The generated completion.
    """
    return Complete(model, prompt).replace("$", "\$")

def make_chat_history_summary(chat_history, question):
    """
    Generate a summary of the chat history combined with the current question to extend the query
    context. Use the language model to generate this summary.

    Args:
        chat_history (str): The chat history to include in the summary.
        question (str): The current user question to extend with the chat history.

    Returns:
        str: The generated summary of the chat history and question.
    """
    prompt = f"""
        [INST]
        Based on the chat history below and the question, generate a query that extend the question
        with the chat history provided. The query should be in natural language.
        Do not consider the **Sources:** section of responses in the chat history
        Do not consider the **Additional Questions:** section of responses in the chat history
        Answer with only the query. Do not add any explanation.

        <chat_history>
        {chat_history}
        </chat_history>
        <question>
        {question}
        </question>
        [/INST]
    """

    summary = complete(st.session_state.model_name, prompt)

    if st.session_state.debug:
        st.sidebar.text_area(
            "Chat history summary", summary.replace("$", "\$"), height=150
        )

    return summary


def create_prompt(user_question):
    """
    Create a prompt for the language model by combining the user question with context retrieved
    from the cortex search service and chat history (if enabled). Format the prompt according to
    the expected input format of the model.

    Args:
        user_question (str): The user's question to generate a prompt for.

    Returns:
        str: The generated prompt for the language model.
    """
    if st.session_state.use_chat_history:
        chat_history = get_chat_history()
        if chat_history != []:
            question_summary = make_chat_history_summary(chat_history, user_question)
            prompt_context = query_cortex_search_service(question_summary)
        else:
            prompt_context = query_cortex_search_service(user_question)
    else:
        prompt_context = query_cortex_search_service(user_question)
        chat_history = ""

    prompt = f"""
[INST]
# ROLE #
You are an expert AI assistant powered by Snowflake Cortex. You are designed to support EMS personnel in Michigan by providing accurate and context-specific answers.

# TASK #
When a user asks a question, you will be provided with:
1. Relevant text from the *State of Michigan EMS Protocol Suite* enclosed within <documents> and </documents> tags.
2. The user's chat history enclosed within <chat_history> and </chat_history> tags.

Your task is to:
- Use the provided context and chat history to generate a precise, complete, and relevant response to the user's question.
- Follow the rules and format outlined below.

# RULES #
1. **Context-Only Responses**: Use only the information provided in the <documents> tags to answer the question. Do not rely on prior knowledge or fabricate information.
2. **No References to Context or Chat History**: Do not explicitly mention "context" or "chat history" in your response.
3. **Citations**: Cite the document titles, page numbers, and sections used for your response under a **Sources** section. 
   - Example: *Document Name, Page X (Section Y)*.
   - Only include sources if you can confidently answer the question.
4. **Unanswerable Questions**: If the context does not provide an answer, respond with: "I don't know the answer to that question."
5. **Response Style**:
   - Ensure clarity, coherence, and relevance.
   - Use bullet points or markdown formatting when appropriate.

# RESPONSE FORMAT #
Generate your response by following these steps:
1. Break down the user's question into smaller sub-questions or directives if necessary.
2. Identify and extract the most relevant information from the context for each sub-question/directive.
3. Draft a complete response using this information while avoiding redundancy or irrelevant details.
4. Refine your draft for accuracy, clarity, and relevance.

# OUTPUT REQUIREMENTS #
1. Provide a clear and concise answer to the user's question.
2. Include a **Sources** section (if applicable) listing all references used for your response.
3. End your response with three related follow-up questions under a **Additional Questions** section.

<chat_history>
{chat_history}
</chat_history>
<documents>
{prompt_context}
</documents>
<question>
{user_question}
</question>
[/INST]
Answer:
"""
    return prompt


def main():
    st.title(f":ambulance: MI EMS Protocol Assistant")
    with st.expander("Disclaimer"):
        st.warning("""This AI-powered chat experience is designed to assist with general information and inquiries. Please note that the information provided may not always be up-to-date, accurate, or applicable to your specific circumstances. For personalized advice or critical information, consult a qualified professional. The responses provided do not constitute legal, medical, financial, or professional advice. Use this chat experience at your own risk. Do not use this chat experience in emergency situations.""")

    init_service_metadata()
    init_config_options()
    init_messages()

    icons = {"assistant": "🤖", "user": "🧑‍⚕️"}

    # Display chat messages from history on app rerun
    for message in st.session_state.messages:
        with st.chat_message(message["role"], avatar=icons[message["role"]]):
            st.markdown(message["content"])

    disable_chat = (
        "service_metadata" not in st.session_state
        or len(st.session_state.service_metadata) == 0
    )
    if question := st.chat_input("Ask a question...", key="chat_input", disabled=disable_chat):
        # Add user message to chat history
        st.session_state.messages.append({"role": "user", "content": question})
        # Display user message in chat message container
        with st.chat_message("user", avatar=icons["user"]):
            st.markdown(question.replace("$", "\$"))


        # Display assistant response in chat message container
        with st.chat_message("assistant", avatar=icons["assistant"]):
            message_placeholder = st.empty()
            question = question.replace("'", "")
            with st.spinner("Researching..."):
                generated_response = complete(
                    st.session_state.model_name, create_prompt(question)
                )
                message_placeholder.markdown(generated_response)

        st.session_state.messages.append(
            {"role": "assistant", "content": generated_response}
        )


if __name__ == "__main__":
    main()
   
