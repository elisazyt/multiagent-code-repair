# Multi-Agent LLM System for Program Repair

This is an automated program repair tool which patches Java bugs using a multi-agent LLM system. Agents are provided with various prompts and tools to explore the codebase by parsing the program, performing static analysis, and retrieving relevant context via lexical and semantic search. Agent interactions are implemented using [AutoGen Core](https://microsoft.github.io/autogen/stable//user-guide/core-user-guide/index.html).

This implementation is a significant extension of the frameworks described at the following links:
- [Repairing Bugs with the Introduction of New Variables: A Multi-Agent Large Language Model](https://dl.acm.org/doi/10.1145/3658644.3691412) (ACM CCS 2024)
- [Patching Multi-Location Bugs: A Multi-Agent Large Language Model Framework for Automated Code Repair](https://www.societyforscience.org/regeneron-sts/2025-student-finalists/elisa-zhang/) (Regeneron STS 2025)

> Preliminary results are available at the links above. Note that they use the `gpt-4o-mini` model and are more limited in scope and complexity compared to this current implementation. Since I'm no longer collaborating with George Mason University on this project, it's now a side project with a practically nonexistent budget. This means running experiments across all 395 bugs in Defects4J with a SOTA model isn't feasible, so exact performance metrics are currently unavailable.

This project is currently tailored to the [Defects4J dataset](https://dl.acm.org/doi/10.1145/2610384.2628055). All bugs and patches can be found in the [Defects4J Dissection](https://program-repair.org/defects4j-dissection/#!/).

---

## Repository Structure

```text
multiagent_code_repair
├── src
│   ├── agents
│   │   ├── __init__.py
│   │   ├── agents.py
│   │   ├── data_structures
│   │   │   ├── bugdict_helpers.py
│   │   │   ├── data_classes.py
│   │   │   └── dicts.py
│   │   ├── helpers
│   │   │   ├── agent_helpers.py
│   │   │   ├── context_retrieval_functions.py
│   │   │   ├── fault_localization.py
│   │   │   ├── function_call_schema.py
│   │   │   └── patch_utils.py
│   │   └── prompts.py
│   ├── defects4j_utils.py
│   ├── main.py
│   └── tools
│       ├── __init__.py
│       ├── context_retrieval
│       │   ├── __init__.py
│       │   ├── parsing_retrieval_funcs
│       │   │   ├── __init__.py
│       │   │   ├── context_retrieval_implementations.py
│       │   │   ├── joern_session.py
│       │   │   ├── joern_utils.py
│       │   │   └── tree_sitter_utils.py
│       │   └── vector_retrieval
│       │       ├── __init__.py
│       │       ├── bm25_search.py
│       │       ├── bm25_utils.py
│       │       ├── unixcoder.py
│       │       └── unixcoder_retrieval.py
│       └── test_suites
│           ├── __init__.py
│           ├── test_suites.py
│           └── test_suites_helpers.py
├── .gitignore
├── Dockerfile
├── README.md
└── requirements.txt
```

---

## Overview

Below is a brief summary of this project. For more details on the architecture and design choices, [refer to the links above](#multi-agent-llm-system-for-apr).

**Input:** Defects4J project name and ID

**Output:**
- Candidate patches, chat history, and generated patches (one per agent)
- An `admin_agent.txt` file which tracks the entire message thread and tool calls across all agents
- Directories created during tool calls (e.g. the Joern workspace, Defects4J checkout, BM25 index)
- The patched .java source code file(s)

**Agents:** This multi-agent system consists of 1 admin agent, 4 patching agents, 1 context retrieval agent, 1 summary agent, 1 testing agent, and 1 patch selection agent:
- **Admin agent**: orchestrates all agents by routing and logging messages from one agent to another
- **Patching agents**: generate patches in parallel, given different prompts and tools
- **Context retrieval agent**: performs context retrieval via tool calls and passes the retrieved context to the corresponding patching agent. The patching agent can request that the context retrieval agent perform the following on demand:
    - Extract syntactic information via AST traversal
    - Perform control flow analysis via code property graphs
    - Retrieve top-k relevant code/text snippets via BM25 search
    - Retrieve top-k relevant code snippets via semantic search using UniXcoder embeddings
- **Summary agent**: condenses the context retrieval agent's results before sending it to the patching agent
- **Testing agent**: runs the Defects4J test suites and returns the failing test information, if applicable
- **Patch selection agent**: selects the best patch out of all candidate patches to return

---

## Usage
To generate a patch for a bug in Defects4J, configs can be specified via command line arguments and the program can be run in a Docker container.

### API key and model:
This implementation currently only supports OpenAI models. For other models that AutoGen supports, [see here](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/models.html). Switching models should not be too difficult as it only requires changing the model client.
The most straightforward way to set the API key and model is by creating a `.env` file with the following contents:
```bash
OPENAI_API_KEY=<api-key>
GPT_MODEL=<model-name>
```
To make these variables available in a Docker container, add `--env-file .env` as an argument when running the container.

### Build and run the docker image:
```bash
docker build -t <image-name> </path/to/repo>
docker run --name <container-name> --env-file .env -v <path/to/results/root>:/projects/results <image-name> --results-root /projects/results --project-name <name> --bug-id <id> --num-patching-attempts <x> --num-retrieval-rounds <y>
```
> All command line arguments from `--results-root` onward have default values (defined in `src/main.py`). However, the user is recommended to override the defaults with their own arguments whenever possible.
> - `<path/to/results/root>:/projects/results` mounts the specified folder on the user's local machine to `/projects/results` in the container. This allows all the message histories, patches, and tool calls to be populated on the user's local machine even after the container finishes running or is deleted
> - `--project-name` and `--bug-id` specify which program to patch
> - `--num-patching-attempts` and `--num-retrieval-rounds` have default values of 3 and 2, respectively, but the user can adjust accordingly based on time and cost constraints
