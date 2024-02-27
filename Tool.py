import os
import logging
import dotenv
from stqdm import stqdm

import streamlit as st
import streamlit.components.v1 as components
from streamlit_tags import st_tags
from annotated_text import annotated_text
import pandas as pd

from presidio_helpers import (
    analyzer_engine,
    analyze,
    anonymize,
    annotate,
    get_supported_entities
)

from application_functions import (
    extract_text_from_file,
    DownloadManager
)

dotenv.load_dotenv()

# Set up logging
# logging.basicConfig(level=logging.DEBUG,
                #    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PII Tool") 

#model selection
st_ta_key = st_ta_endpoint = ""

model_list = [
    "spaCy/en_core_web_lg",
    "flair/ner-english-large",
    "HuggingFace/obi/deid_roberta_i2b2",
    "HuggingFace/StanfordAIMI/stanford-deidentifier-base",
    "stanza/en"
]

st_model = st.sidebar.selectbox(
    "Select NER Model",
    model_list,
    index=0,
    help="Select the NER model to use for entity identification and PII extraction / redaction."
)

st_model_package = st_model.split("/")[0]

# Remove package prefix (if needed)
st_model = (
    st_model
    if st_model_package.lower() not in ("spacy", "stanza", "huggingface")
    else "/".join(st_model.split("/")[1:])
)
st.sidebar.warning("Some models might take some time to download.")

analyzer_params = (st_model_package, st_model, st_ta_key, st_ta_endpoint)
# logger.debug(f"analyzer_params: {analyzer_params}")

#PII extraction tools
st_operator = st.sidebar.selectbox(
    "Select PII Extraction Tool",
    ["replace", "redact", "mask"],
    index=0,
    help="""
    Select which manipulation to the text is requested after PII has been identified.\n
    - Replace: Replace the PII text with a constant, e.g. <PERSON> \n
    - Redact: Completely remove the PII text\n
    - Mask: Replaces a requested number of characters with an asterisk (or other character) \n
"""
)

st_mask_char ="*"
st_number_of_chars = 15

if st_operator == "mask":
    st_number_of_chars = st.sidebar.number_input(
        "number of chars", value=st_number_of_chars, min_value=0, max_value=100
    )
    st_mask_char = st.sidebar.text_input(
        "Mask character", value=st_mask_char, max_chars=1
    )

#logger.debug(f"Selected model: {st_model}")
#logger.debug(f"Selected operator: {st_operator}")

# Allowlist and denylist
st_deny_allow_expander = st.sidebar.expander(
    "Allow and deny lists",
    expanded=False,
)

with st_deny_allow_expander:
    st_allow_list = st_tags(
        label="Add words to the allowlist", text="Enter word and press enter."
    )
    st.caption(
        "Allowlists contain words that are not considered PII, but are detected as such."
    )

    st_deny_list = st_tags(
        label="Add words to the denylist", text="Enter word and press enter."
    )
    st.caption(
        "Denylists contain words that are considered PII, but are not detected as such."
    )

#entity selection
st_entities_expander = st.sidebar.expander("Choose entities to look for")
st_entities = st_entities_expander.multiselect(
    label="Which entities to look for?",
    options=get_supported_entities(*analyzer_params),
    default=list(get_supported_entities(*analyzer_params)),
    help="Limit the list of PII entities detected. "
    "This list is dynamic and based on the NER model and registered recognizers. "
    "More information can be found here: https://microsoft.github.io/presidio/analyzer/adding_recognizers/",
)

#callback function to update the session state
def update_output_format():
    st.session_state['output_format'] = st.session_state['output_format']

# Main function
def main():
    #bool that saves the session state on whether the analysis was done
    if 'analysis_done' not in st.session_state:
        st.session_state['analysis_done'] = False
    #saves the session state as dictionary output, but only focuses on the text output
    if 'anonymized_results' not in st.session_state:
        st.session_state['anonymized_results'] = None
    #saves the session state as dictionary output, but has the analyzed results included
    if 'anonymyzed_results_with_analysis' not in st.session_state:
        st.session_state['anonymyzed_results_with_analysis'] = None
    #saves the session state as dictionary output, but only focuses on the table output / then reorganizes it into a dataframe
    if 'results_table' not in st.session_state:
        st.session_state['results_table'] = None
    #saves the session state as dictionary output, but only focuses on the preview output
    if 'output_preview' not in st.session_state:
        st.session_state['output_preview'] = None
    if 'highlighting_done' not in st.session_state:
        st.session_state['highlighting_done'] = False
    
    #output bool holder
    if 'output_format' not in st.session_state:
        st.session_state['output_format'] = 'Text'
    
    #download session state
    if 'download_done' not in st.session_state:
        st.session_state['download_done'] = False
    
    #data session state
    if 'upload_file' not in st.session_state:
        st.session_state['upload_file'] = None

    #subheader holder
    subheader_call = ""

    #Markdown holder
    markdown_dict = {}

    #preview limit
    preview_limit = 1000

    #load
    analyzer_engine(*analyzer_params)

    st.title("Data Anonymization App")
    with st.expander("Expand this for more information ", expanded=False):
        st.info(
                """This app is designed to anonymize PII data in spreadsheets (most commonly Excel). The app utilizes the Presidio library to identify PII in the sheets, and then anonymizes the data based on the user's preferences. """)
        st.warning("""
                **Important Note**: This app is designed to be used with spreadsheets, and is not designed to handle large amounts of data. Please use caution when uploading large files, as the app may crash or become unresponsive. Currently the appliaction is limited to a 5MB file size. If you have a larger file, please message me.""")
        st.warning("""Some models perform better than others. If the desired results are not achieved, please try a different model. I've had success with various models, "HuggingFace/obi/deid_roberta_i2b2" and "HuggingFace/StanfordAIMI/stanford-deidentifier-base" in particular.
        """)


    # Sidebar for NER Model Configurations
    with st.sidebar:
        st.subheader("Adjustable Settings")
        # ner_model = st_model
        de_ident_method = st_operator
        acceptance_threshold = st.slider("Acceptance Threshold", 0.0, 1.0, 0.0)
        allow_list = st_allow_list
        deny_list = st_deny_list
        entity_choices = st_entities

    # Main Window for Input/Output
    
    uploaded_file = None
    
    uploaded_file = st.file_uploader("Upload a file", type=["xlsx", "xls"])
    st.session_state['upload_file'] = uploaded_file

    if st.session_state['upload_file'] is not None:
        text_to_process = extract_text_from_file(uploaded_file)
        file_extension = uploaded_file.name.split(".")[-1].lower() if uploaded_file else None
    else:
        st.session_state['upload_file'] = None

    #button columns
    col1, col2, col3 = st.columns(3)

    #container for the highlighting and anonymizing buttons
    output_container = st.container()


    #The Highlight Button
    with col1:
        if st.button(
                label="Highlight the PII",
                help="Utilizing Streamlit and Presidio, we're able to initially identify what PII exists in the text / uploaded document."
                    ):
            if uploaded_file is None:
                st.warning("Please upload a file or enter text to process.")
            else:
                if isinstance(text_to_process, dict):
                    if file_extension in ["xlsx", "xls"]:
                        for sheet_name, total_text in text_to_process.items():
                            subheader_call = (f"Highlighted Results for {sheet_name}:")
                            for col_name, sub_text in stqdm(total_text.items(), desc="Processing columns in sheets"):
                                col_header = (f'''
                                    <h3 style="font-size: 20px; margin-bottom: 0;">{col_name}</h3>
                                    <hr style="margin-top: 0; border: 1px solid #382c29;">
                                    ''')
                                markdown_dict[col_header] = []
                                for cell_text in sub_text:
                                    if cell_text is None or cell_text.strip()=='':
                                        pass
                                    elif cell_text is not None and cell_text.strip()!='':
                                        analyzed_results = analyze(
                                            *analyzer_params,
                                            text=cell_text,
                                            entities=entity_choices,
                                            language='en',
                                            score_threshold=acceptance_threshold,
                                            allow_list=allow_list,
                                            deny_list=deny_list,
                                            )
                                        if analyzed_results:
                                            annotated_tokens = annotate(text=cell_text, analyze_results=analyzed_results)
                                            markdown_dict[col_header].append(annotated_tokens)
                                            st.session_state['highlighting_done'] = True
                                            st.session_state['analysis_done'] = False
                                    else:
                                        st.warning("No results found.")
    with col2:
        if st.button(
                label="Anonymize",
                help="Anonymize the PII in the text / uploaded document."
                ):
            anonymized_results_dict = {}
            ner_df = pd.DataFrame()
            aggregated_texts = []
            if uploaded_file is None:
                st.warning("Please upload a file or enter text to process.")
            else:
                if isinstance(text_to_process, dict):
                    if file_extension in ["xlsx", "xls"]:
                        for sheet_name, total_text in text_to_process.items():
                            anonymized_sheet = {}
                            for col_name, sub_text in stqdm(total_text.items(), desc="Processing columns in sheets"):
                                anonymized_columns = []
                                for cell_text in sub_text:
                                    if cell_text is None or cell_text.strip()=='':
                                        anonymized_columns.append('')
                                    elif cell_text is not None and cell_text.strip()!='':
                                        analyzed_results = analyze(
                                            *analyzer_params,
                                            text=cell_text,
                                            entities=entity_choices,
                                            language='en',
                                            score_threshold=acceptance_threshold,
                                            allow_list=allow_list,
                                            deny_list=deny_list,
                                            )
                                        anonymized_results = anonymize(
                                            text=cell_text,
                                            analyze_results=analyzed_results,
                                            operator=de_ident_method,
                                            mask_char=st_mask_char,
                                            number_of_chars=st_number_of_chars,
                                            )
                                        if analyzed_results:
                                            #DF Building
                                            df = pd.DataFrame.from_records([r.to_dict() for r in analyzed_results])
                                            df["text"] = [cell_text[res.start : res.end] for res in analyzed_results]
                                            expected_columns = ["entity_type","text","start","end","score"]
                                            missing_columns = [col for col in expected_columns if col not in df.columns]

                                            if not missing_columns:
                                                df_subset = df[expected_columns].rename(
                                                    {
                                                        "entity_type": "Entity Type",
                                                        "text": "Text",
                                                        "start": "Start",
                                                        "end": "End",
                                                        "score": "Confidence"
                                                    },
                                                    axis=1
                                                )
                                                df_subset["Text"] = [cell_text[res.start : res.end] for res in analyzed_results]
                                                ner_df = pd.concat([ner_df, df_subset], ignore_index=True)
                                                st.session_state['results_table'] = ner_df
                                                st.session_state['analysis_done'] = True
                                                st.session_state['highlighting_done'] = False
                                            else:
                                                st.warning(f"Missing columns: {missing_columns}")
                                    else:
                                        st.warning("No analyzed results found.")
                                    #Appending Results
                                    anonymized_columns.append(anonymized_results.text)
                                anonymized_sheet[col_name] = anonymized_columns
                            anonymized_results_dict[sheet_name] = anonymized_sheet
                        #Anonymized Results Building
                        if anonymized_results_dict[sheet_name]:
                            for value in anonymized_results_dict.values():
                                if isinstance(value, dict):
                                    for subtext in value.values():
                                        for cell_text in sub_text:
                                            aggregated_texts.append(cell_text)
                                else:
                                    aggregated_texts.append(subtext)
                        st.session_state['anonymized_results'] = anonymized_results_dict
                        st.session_state['output_preview'] = "\n\n".join(aggregated_texts)
    
    with col3:
        # Check if analysis is done and results are available
        if st.session_state['analysis_done'] and st.session_state['anonymized_results'] is not None:
            # Set output format to Excel directly since no other formats are needed
            st.session_state['output_format'] = 'Excel'
            
            # Check if there is an uploaded file to determine the file type
            if uploaded_file is not None:
                file_type = uploaded_file.type  # Though not used since format is fixed to Excel, you might need it for other purposes
                format_type = 'Excel'  # Set format type to Excel directly
                
                # Initialize the DownloadManager with preprocessed data and desired format_type (Excel)
                manager = DownloadManager(st.session_state['anonymized_results'], file_type, format_type)
        
                # Prepare the data for Excel format
                download_data = manager.prepare()
                
                if download_data is not None:
                    # Set file name and MIME type for Excel
                    file_name = "anonymized.xlsx"
                    mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    
                    # Provide download button for Excel file
                    st.download_button(
                        label="Download Excel",  # Changed label to directly indicate Excel download
                        data=download_data,
                        file_name=file_name,
                        mime=mime_type
                    )
                    st.session_state['download_done'] = True

    with output_container:
        st.empty()

    if not uploaded_file:
        output_container.empty()
        st.session_state['analysis_done'] = False
        st.session_state['anonymized_results'] = None
        st.session_state['highlighting_done'] = False
    else:
        if uploaded_file:
            with output_container:
                if st.session_state.get('highlighting_done', False):
                    st.subheader(subheader_call)
                    if file_extension in ["xlsx", "xls", "pdf"]:
                        for page, tokens in markdown_dict.items():
                            st.markdown(page, unsafe_allow_html=True)
                            for annotated_tokens in tokens:
                                annotated_text(*annotated_tokens)
                elif st.session_state.get('analysis_done', False):
                    #st.write(st.session_state['anonymized_results'])
                    st.subheader("Anonymized Results: Text Preview")
                    st.text_area(label="anon results",value=st.session_state.get('output_preview','')[:preview_limit], height=200, max_chars=1000, disabled=True, label_visibility="hidden")
                    st.subheader("Anonymized Results: Table Preview")
                    if 'results_table' in st.session_state and st.session_state['results_table'] is not None:
                        st.dataframe(data=st.session_state['results_table'], use_container_width=True)

# Run the app
if __name__ == "__main__":
    main()

components.html(
    """
    <script type="text/javascript">
    (function(c,l,a,r,i,t,y){
        c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};
        t=l.createElement(r);t.async=1;t.src="https://www.clarity.ms/tag/"+i;
        y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);
    })(window, document, "clarity", "script", "h7f8bp42n8");
    </script>
    """
)
