import os

from components.extract_compoment import convert_to_markdown, extract_metadata, write_to_file

data_folder = "./data/"
data_output_folder = "./data-output/"

if __name__ == "__main__":
    for file in os.listdir(data_folder):
        if file.endswith(".pdf"):
            input_file = os.path.join(data_folder, file)
            output_file = os.path.join(data_output_folder, f"{os.path.splitext(file)[0]}.md")

            text_result = convert_to_markdown(input_file)
            doc_metadata = extract_metadata(input_file)
            write_to_file(output_file, doc_metadata, text_result)
