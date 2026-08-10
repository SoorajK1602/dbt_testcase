import streamlit as st
import zipfile
import tempfile
import os
import re
import openai
import json
if 'openai_response_cache' not in st.session_state:
    st.session_state.openai_response_cache = {}



st.set_page_config(page_title="DBT Data Test Case Generator")
st.title("🧪 DBT Data Test Case Generator")

openai.api_key = ""  # Replace this

uploaded_zip = st.file_uploader("Upload your DBT models ZIP file", type=["zip"])

@st.cache_data(show_spinner=False)
def get_llm_test_suggestions(col_name, data_type, not_null):
    prompt = f"""
You are an expert in DBT data testing. Given this column definition:

- Column name: {col_name}
- Data type: {data_type}
- Nullability: {"NOT NULL" if not_null else "Nullable"}

Recommend which DBT data tests should be applied to this column using the YAML-style DBT test syntax.

Return a JSON list of tests. Examples: ["not_null", "unique"]

Important:
- Only include `not_null` if the column is NOT NULL *and* clearly required (like `id`, `email`, `username`, `login`, etc).
- If the column looks optional (e.g. `MiddleName`, `Comment`, `PhonePassword`, etc.), do NOT include `not_null`.
- Include a comment test note for fields that seem optional or unclear.

If no tests apply, return an empty list.
"""
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        json_array = content[content.find('['):content.rfind(']')+1]
        return json.loads(json_array)
    except Exception as e:
        return [f"error: {str(e)}"]

def get_materialized_type(sql_text):
    """
    Extract the materialized type from dbt config block if present.
    Returns lowercased materialized type or None.
    """
    match = re.search(r'\{\{\s*config\(\s*materialized\s*=\s*[\'"](\w+)[\'"]', sql_text, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return None

if uploaded_zip:
    import tempfile
    import os
    import zipfile
    import streamlit as st

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "models.zip")
        with open(zip_path, "wb") as f:
            f.write(uploaded_zip.getbuffer())

        exclude_files = {"report_all_account.sql", "v_easy_nl_all_profiles.sql", 
                         "test.sql", "time_filter.sql", "unit_test.sql"}
        exclude_folders = {"dbt_packages"}  # completely ignore this folder

        model_files = []

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                # Normalize slashes and lowercase for comparison
                member_norm = member.replace("\\", "/")
                member_lower = member_norm.lower()

                # Skip any files inside excluded folders (nested too)
                if any(f"/{folder.lower()}/" in f"/{member_lower}/" for folder in exclude_folders):
                    continue

                # Skip non-SQL files
                if not member_lower.endswith(".sql"):
                    continue

                # Skip specific files by basename
                if os.path.basename(member_lower) in exclude_files:
                    continue

                # Add allowed SQL files
                model_files.append(member_norm)

        if not model_files:
            st.error("No SQL models found in the ZIP!")
        else:
            # Show dropdown with only file names
            selected_model = st.selectbox("Choose a model", [os.path.basename(f) for f in model_files])
            selected_model_full = next(f for f in model_files if os.path.basename(f) == selected_model)

            # Extract only the selected file
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extract(selected_model_full, tmpdir)

            selected_model_path = os.path.join(tmpdir, selected_model_full)

            # Read and display SQL
            with open(selected_model_path, "r") as f:
                model_sql = f.read()
            st.subheader("📄 Selected Model SQL")
            st.code(model_sql, language="sql")

            model_table = os.path.splitext(selected_model)[0]
            st.info(f"Table name: `{model_table}`")




            import re
            import streamlit as st

            st.subheader("📥 Paste your DDL dump text here")
            ddl_text = st.text_area(
                "Paste full SQL dump (DDL statements, plain text):",
                height=300,
                placeholder="E.g., CREATE TABLE ... ; ALTER TABLE ... ;",
            )

            if ddl_text.strip():
                columns_info = []

                # --- Regex for CREATE TABLE ---
                table_regex = re.compile(
                    r'CREATE\s+TABLE\s+(?:IF NOT EXISTS\s+)?("?[\w\.]+"?)\s*\((.*?)\);',
                    re.IGNORECASE | re.DOTALL
                )

                # --- Regex for CREATE VIEW / MATERIALIZED VIEW ---
                view_regex = re.compile(
                    r'CREATE\s+(?:MATERIALIZED\s+)?VIEW\s+(?P<name>"?[\w\.]+"?)\s+AS\s+(?P<body>.*?)(?:;|$)',
                    re.IGNORECASE | re.DOTALL
                )

                # Auto-detect the first table or view
                # Keep model_table as the uploaded SQL file name for YAML
                ddl_table_name = None

                table_match = table_regex.search(ddl_text)
                view_match = view_regex.search(ddl_text)

                if table_match:
                    ddl_table_name = table_match.group(1).replace('"', '').split('.')[-1]
                elif view_match:
                    ddl_table_name = view_match.group("name").replace('"', '').split('.')[-1]


                if model_table:
                    # --- Parse CREATE TABLE columns ---
                    for match in table_regex.finditer(ddl_text):
                        raw_table_name = match.group(1).replace('"', '')
                        base_table = raw_table_name.split('.')[-1]
                        if base_table.lower() == ddl_table_name.lower():
                            columns_block = match.group(2)
                            for line in columns_block.split(','):
                                line_clean = line.strip()
                                col_match = re.match(
                                    r'\s*("([^"]+)"|[\w]+)\s+([^\s,]+)(.*)', line_clean, re.IGNORECASE
                                )
                                if col_match:
                                    col_name = col_match.group(2) or col_match.group(1)
                                    data_type = col_match.group(3)
                                    rest = col_match.group(4).upper()
                                    common_required_fields = ["login", "id", "email", "username"]
                                    not_null = any(key in col_name.lower() for key in common_required_fields) or 'NOT NULL' in rest
                                    columns_info.append({
                                        "col_name": col_name,
                                        "data_type": data_type,
                                        "not_null": not_null
                                    })
                            break

                    # --- Parse CREATE VIEW columns ---
                    for match in view_regex.finditer(ddl_text):
                        raw_view_name = match.group("name").replace('"', '')
                        base_view = raw_view_name.split('.')[-1]
                        if base_table.lower() == ddl_table_name.lower():
                            body = match.group("body")
                            select_match = re.search(r'SELECT\s+(.*?)(?=\bFROM\b)', body, re.IGNORECASE | re.DOTALL)
                            if select_match:
                                select_part = select_match.group(1)
                                col_matches = re.findall(
                                    r'(?:AS\s+"([^"]+)")'           # AS "Alias"
                                    r'|(?:"([^"]+)")'               # "ColumnName"
                                    r'|(?:AS\s+([a-zA-Z_][\w]*))'   # AS alias_no_quotes
                                    r'|([a-zA-Z_][\w]*)\s*(?=,|$)', # bare columns
                                    select_part,
                                    re.IGNORECASE
                                )
                                seen = set()
                                for quoted_alias, quoted_col, unquoted_alias, bare_col in col_matches:
                                    col_name = quoted_alias or quoted_col or unquoted_alias or bare_col
                                    if col_name and col_name.lower() not in seen:
                                        seen.add(col_name.lower())
                                        columns_info.append({
                                            "col_name": col_name,
                                            "data_type": None,
                                            "not_null": False
                                        })
                            break

                    if not columns_info:
                        st.warning("❌ No table or view found, or no columns parsed.")
                    else:
                        st.success(f"✅ Detected the columns")
                     

                    prompt = f"""
                    You are an expert SQL parser and dbt testing assistant.

                    Task:
                    Carefully analyze the provided SQL model and its table schema. Generate a JSON array ONLY, adhering strictly to the output format and inference rules below.

                    Output Format:
                    - Output exactly one valid JSON array, nothing else.
                    - Each array item is an object with EXACTLY these keys: "column_name" (string), "data_type" (string, always double-quoted), "inferred_not_null" (boolean), and "suggested_tests" (array of strings).
                    - Do NOT include any extra text, explanation, comments, markdown, or trailing commas.
                    - JSON must be fully syntactically correct and parsable.
                    - If the same model is selected more than once, you MUST produce the exact same JSON array result as the first time. No changes or variations allowed.

                    Inference Rules:
                    - Set inferred_not_null = true ONLY IF any of the following are true based on the SQL logic:
                    1. The column appears in JOIN, WHERE, GROUP BY, or ORDER BY clauses.
                    - The column appears in JOIN, WHERE, GROUP BY, or ORDER BY clauses AND the join type is INNER JOIN (or an equivalent filter that guarantees matches). Do NOT infer not_null for columns coming from FULL OUTER, LEFT, or RIGHT joins unless there is an explicit WHERE condition enforcing non-nullness.
                    2. Any column that appears in an arithmetic operation—either as an operand or as the resulting expression—must be inferred_not_null = true.
                    3. The column is used in a CAST expression AND that same column also appears in JOIN or WHERE clauses.
                    4. The column is used in AGGREGATE FUNCTIONS like sum, *, count(*), etc.
                    - Columns derived from aggregate functions (e.g., sum, count) can be inferred_not_null = true only if they are not later exposed to a FULL OUTER, LEFT, or RIGHT JOIN that could introduce nulls, unless there is an explicit WHERE condition filtering out nulls for that column.
                    5. # Add this to your prompt before passing to the model # Emphasize that arithmetic operands must be not_null
                    - "Columns used in arithmetic expressions (either as operands or in the resulting expression) MUST be inferred_not_null = true. For example: t3.\"Volume\" and t3.\"ContractSize\" in (t3.\"Volume\" / 10000::numeric)::double precision * t3.\"ContractSize\"."
                    - Columns that are the result of arithmetic operations on one or more not-null columns should also have inferred_not_null = true.
                    - Do NOT set inferred_not_null true for CAST usage alone.
                    - If inferred_not_null = true, suggested_tests must include "not_null".
                    - Do NOT make any assumptions; mark inferred_not_null = true only if SQL logic explicitly guarantees it.

                    Uniqueness Rules:
                    - Add "unique" to suggested_tests ONLY if a column is part of a GROUP BY that uniquely identifies rows BY ITSELF according to the SQL logic.
                    - Do NOT mark uniqueness for columns that require a composite key.
                    - Columns derived from aggregate functions (e.g. count(*)) are NOT NULL at aggregate level.
                    - If the model uses FULL OUTER, LEFT, or RIGHT JOINs that can introduce NULLs, do NOT infer not_null on those columns.
                    - Always consider join types and their effects on nullability carefully.
                    - The model uses unique_key = "<column_name>" for that column.
                    - Do NOT make any assumptions; mark "unique" only if SQL logic explicitly guarantees it.

                    Additional Instructions:
                    - Be deterministic and consistent; identical inputs MUST produce identical outputs every time.
                    - Strictly follow the SQL conditions and give test cases. Don't assume and give.
                    - Absolutely no hallucinations or assumptions beyond what the SQL and schema explicitly imply.
                    - Follow all rules precisely and do not deviate.

                    ### SQL MODEL:
                    {model_sql}

                    ### TABLE SCHEMA:
                    {json.dumps(columns_info, indent=2)}

                    Output ONLY the JSON array, exactly as specified, no additional text or formatting.
                    """




                    import hashlib
                    import json

                    def get_cache_key(model_table, model_sql, columns_info):
                        combined_str = model_table.lower() + model_sql + json.dumps(columns_info, sort_keys=True)
                        return hashlib.sha256(combined_str.encode('utf-8')).hexdigest()

                    cache_key = get_cache_key(model_table, model_sql, columns_info)

                    if cache_key in st.session_state.openai_response_cache:
                        df, yaml_content = st.session_state.openai_response_cache[cache_key]
                        st.info(f"Using cached analysis")
                    else:
                        df, yaml_content = None, None

                    if st.button("Run analysis and save to cache") or (df is not None and yaml_content is not None):
                        if df is None or yaml_content is None:
                            # Run OpenAI call only when button clicked and cache is empty
                            try:
                                response = openai.chat.completions.create(
                                    model="gpt-4",
                                    messages=[{"role": "user", "content": prompt}],
                                    temperature=0,
                                    max_tokens=3000,
                                )
                                content = response.choices[0].message.content.strip()

                                import re
                                import json

                                start = content.find('[')
                                end = content.rfind(']') + 1
                                if start == -1 or end == -1:
                                    raise ValueError(f"Could not find JSON array in GPT response:\n{content}")

                                json_str = content[start:end]

                                json_str = re.sub(
                                    r'("data_type"\s*:\s*)([a-zA-Z_]+(?:\([0-9, ]+\))?)',
                                    r'\1"\2"',
                                    json_str
                                )
                                json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
                                json_str = re.sub(r'\s+', ' ', json_str)

                                parsed = json.loads(json_str)

                                import pandas as pd
                                df = pd.DataFrame(parsed)

                                def generate_dbt_test_yaml(df, model_table):
                                    tests_yaml = {
                                        "version": 2,
                                        "models": [
                                            {
                                                "name": model_table,
                                                "columns": []
                                            }
                                        ]
                                    }

                                    for _, row in df.iterrows():
                                        col_entry = {
                                            "name": row["column_name"],
                                        }
                                        if isinstance(row["suggested_tests"], list) and row["suggested_tests"]:
                                            col_entry["tests"] = row["suggested_tests"]

                                        tests_yaml["models"][0]["columns"].append(col_entry)

                                    import yaml
                                    return yaml.dump(tests_yaml, sort_keys=False)

                                yaml_content = generate_dbt_test_yaml(df, model_table)

                                # Save to cache
                                st.session_state.openai_response_cache[cache_key] = (df, yaml_content)
                                st.success("✅ Analysis saved to cache!")

                            except Exception as e:
                                st.error(f"Error from OpenAI: {str(e)}\nRaw content was:\n{content}")
                                df = None
                                yaml_content = None

                        if df is not None and yaml_content is not None:
                            st.subheader(f"📝 Analysis")
                            st.dataframe(df)

                            st.subheader("📋 Generated dbt test YAML")
                            st.code(yaml_content, language="yaml")

                            st.download_button(
                                label="Download YAML file",
                                data=yaml_content,
                                file_name=f"{model_table}_tests.yml",
                                mime="text/yaml",
                            )
