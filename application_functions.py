import pandas as pd
import xlsxwriter
import io
import logging
import dotenv

dotenv.load_dotenv()

# Set up logging
# logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("PII Tool")

file_type = ""

# Function to extract text from files
def extract_text_from_file(uploaded_file):
    """
    Extract text from uploaded file types.
    :param uploaded_file: file uploaded by user
    """
    # New File Uploader utilizing dictionaries
    extracted_text = {}
    file_type = uploaded_file.type
    if file_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"]:
        xl = pd.ExcelFile(uploaded_file)
        for sheet_name in xl.sheet_names:
            df = xl.parse(sheet_name)
            df.fillna("", inplace=True)
            # For each sheet, store each column's data as a separate string, concatenated with row data
            sheet_data = {col: df[col].astype(str).tolist() for col in df.columns}
            extracted_text[sheet_name] = sheet_data
    return extracted_text


class DownloadManager:
    def __init__(self, data, file_type, format_type):
        self.data = data
        self.file_type = file_type
        self.format_type = format_type
        # Use BytesIO for binary file formats like Excel
        self.output = io.BytesIO() if format_type == "Excel" else io.StringIO()
        # Map MIME types to methods
        self.method_map = {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                "Excel": self.prepare_excel,
            },
            # Add additional file types and formats as needed
        }
    
    def prepare(self):
        # Select the appropriate conversion method based on file_type and format_type
        file_type_map = self.method_map.get(self.file_type, {})
        conversion_method = file_type_map.get(self.format_type)
        if conversion_method:
            conversion_method()
        else:
            raise ValueError(f"Unsupported conversion: {self.file_type} to {self.format_type}")
        return self.output.getvalue()

    def prepare_excel(self):
        workbook = xlsxwriter.Workbook(self.output, {'in_memory': True})
        column_header = workbook.add_format({"align": "center", "valign": "vcenter"})
        cell_format = workbook.add_format({"align": "left", "valign": "vcenter"})
        for sheet_name, sheet_data in self.data.items():
            worksheet = workbook.add_worksheet(sheet_name[:31])  # Limit sheet name length
            for col_index, (col_name, col_data) in enumerate(sheet_data.items()):
                worksheet.write(0, col_index, col_name, column_header)
                for row_index, cell_data in enumerate(col_data, start=1):
                    worksheet.write(row_index, col_index, cell_data, cell_format)
        workbook.close()
        self.output.seek(0)