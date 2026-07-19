import argparse
from pathlib import Path

import pandas as pd


def run(
    input_folder: str = "output/",
    output_file: str = "output/combined.csv",
    add_source_file_column: bool = True,
) -> None:
    folder = Path(input_folder)
    all_dataframes = []

    for file_path in folder.iterdir():
        if file_path.is_file() and file_path.suffix.lower() == ".csv":
            try:
                df = pd.read_csv(file_path)

                if add_source_file_column:
                    df["source_file"] = file_path.name

                all_dataframes.append(df)
                print(f"Loaded: {file_path.name}")
            except Exception as e:
                print(f"Skipped {file_path.name} due to error: {e}")

    if all_dataframes:
        combined_df = pd.concat(all_dataframes, ignore_index=True, sort=False)
        combined_df.to_csv(output_file, index=False)
        print(f"\nDone. Combined {len(all_dataframes)} CSV files into:")
        print(output_file)
    else:
        print("No CSV files found in the folder.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Concatenate every CSV in a folder into one combined CSV.")
    parser.add_argument("--input-dir", default="output/", help="Folder to read CSVs from (default: output/)")
    parser.add_argument("--output", default="output/combined.csv", help="Combined CSV path (default: output/combined.csv)")
    parser.add_argument("--no-source-column", action="store_true", help="Don't add a source_file column")
    args = parser.parse_args()
    run(args.input_dir, args.output, not args.no_source_column)


if __name__ == "__main__":
    main()
