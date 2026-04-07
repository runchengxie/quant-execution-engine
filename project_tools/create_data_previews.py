from pathlib import Path

import pandas as pd


def create_previews():
    """
    Finds all CSV files in the '../data' directory, reads the first 5 data rows
    from each, and saves them to a new .txt file in the same directory.
    """
    try:
        # 1. Define paths
        # Path(__file__) is the current script path (e.g., .../tools/create_top_100_previews.py)
        # .resolve() gets the absolute path
        # .parent gets the parent directory (e.g., .../tools/)
        # .parent.parent gets the project root directory
        project_root = Path(__file__).resolve().parent.parent
        data_dir = project_root / "data"

        print(f"[*] Searching for CSV files in: {data_dir}")

        # 2. Ensure the data directory exists
        if not data_dir.is_dir():
            print(f"[!] Error: Data directory not found at {data_dir}")
            return

        # 3. Find all CSV files
        csv_files = list(data_dir.glob("*.csv"))

        if not csv_files:
            print(f"[*] No CSV files found in {data_dir}.")
            return

        print(f"[*] Found {len(csv_files)} CSV file(s) to process.")

        # 4. Iterate through and process each CSV file
        for csv_path in csv_files:
            print(f"    -> Processing '{csv_path.name}'...")

            try:
                # Use pandas to read the first 5 rows. nrows=5 is efficient and
                # reads only the header and the next 5 rows.
                df = pd.read_csv(
                    csv_path, nrows=5, encoding="utf-8", on_bad_lines="skip"
                )

                # 5. Define the output filename and path
                # csv_path.stem gets the filename without extension (e.g., 'us-balance-quarterly')
                output_filename = f"top_5_sample_{csv_path.stem}.txt"
                output_path = data_dir / output_filename

                # 6. Write the DataFrame to a new file in a readable text format
                # to_string() generates a human-friendly representation
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(df.to_string())

                print(f"    <- Successfully created '{output_filename}'")

            except Exception as e:
                print(f"    [!] Error processing file {csv_path.name}: {e}")

        print("\n[*] Script finished successfully.")

    except Exception as e:
        print(f"[!] An unexpected error occurred: {e}")


# Execute create_previews when running this script directly
if __name__ == "__main__":
    create_previews()
