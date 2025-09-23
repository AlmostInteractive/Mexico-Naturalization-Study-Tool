import subprocess
import sys
import os
import argparse


def setup_questions(input_csv: str, model: str = "llama3.2", subject: str = "Mexican history and culture", keep_distractors: bool = True, batch_size: int = 1):
    """
    Complete workflow: Generate distractors using local LLM and import to database.

    Args:
        input_csv: Path to basic "Question,Answer" CSV file
        model: Local LLM model to use
        subject: Subject matter for context
        keep_distractors: Keep the intermediate distractors CSV file (default: True)
        batch_size: Number of questions per API call
    """

    print("Mexico Study Guide - Question Setup (Local LLM)")
    print("=" * 60)

    # Validate input file exists
    if not os.path.exists(input_csv):
        print(f"ERROR: Input file '{input_csv}' not found")
        return False

    # Generate expected output filename
    base_name = os.path.splitext(input_csv)[0]
    distractors_csv = f"{base_name}_distractors.csv"

    try:
        # Step 1: Generate distractors using local LLM
        print(f"Step 1: Generating AI-powered distractors using local LLM...")
        print(f"Input: {input_csv}")
        print(f"Model: {model}")
        print(f"Subject: {subject}")
        print(f"Batch size: {batch_size}")

        # Build command for local LLM distractor generation
        cmd = [sys.executable, 'create_distractors.py', input_csv]

        if model != "llama3.2":
            cmd.extend(["--model", model])

        if subject != "Mexican history and culture":
            cmd.extend(["--subject", subject])

        if batch_size != 1:
            cmd.extend(["--batch-size", str(batch_size)])

        result1 = subprocess.run(cmd, capture_output=True, text=True)

        if result1.returncode != 0:
            print(f"ERROR generating distractors:")
            print(result1.stderr)
            return False

        print(result1.stdout)

        # Check if distractors file was created
        if not os.path.exists(distractors_csv):
            print(f"ERROR: Expected distractors file '{distractors_csv}' was not created")
            return False

        # Step 2: Import to database
        print(f"\nStep 2: Importing to database...")
        print(f"Distractors file: {distractors_csv}")

        result2 = subprocess.run([
            sys.executable, 'import_distractors.py',
            distractors_csv
        ], capture_output=True, text=True)

        if result2.returncode != 0:
            print(f"ERROR importing to database:")
            print(result2.stderr)
            return False

        print(result2.stdout)

        # Keep the distractors file for inspection and future use
        print(f"\nDistractors file saved: {distractors_csv}")
        print("  - You can inspect the generated distractors in this file")
        print("  - Keep this file as a backup of your enhanced questions")

        print("\nSetup complete! Questions with local AI-generated distractors are ready.")
        print("You can now run 'python app.py' to start the quiz.")

        return True

    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")

        # Clean up intermediate file on error
        if os.path.exists(distractors_csv):
            os.remove(distractors_csv)

        return False


def main():
    parser = argparse.ArgumentParser(
        description="Mexico Study Guide - Local LLM Question Setup Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python setup_questions.py questions.csv
  python setup_questions.py questions.csv --model mistral
  python setup_questions.py questions.csv --subject "World History"
  python setup_questions.py questions.csv --delete-distractors --batch-size 2

Input CSV format:
  "Question","Answer"
  "¿Cuál es la capital de México?","Ciudad de México"
  "¿En qué año fue la Independencia?","1810"

This tool will:
  1. Generate 8 contextual AI-powered distractors for each question using local LLM
  2. Import questions into the quiz database
  3. Set up chunking for progressive learning
  4. Initialize statistics for adaptive learning

Requirements:
  - Ollama installed and running (https://ollama.ai/)
  - Local LLM model downloaded (e.g., ollama pull llama3.2)
  - No API keys or internet required after setup
        """
    )

    parser.add_argument('input_csv', help='Input CSV file (Question,Answer format)')
    parser.add_argument('--model', default='llama3.2',
                       help='Local LLM model to use (default: llama3.2)')
    parser.add_argument('--subject', default='Mexican history and culture',
                       help='Subject matter for context (default: Mexican history and culture)')
    parser.add_argument('--delete-distractors', action='store_true',
                       help='Delete the intermediate distractors CSV file after import (default: keep file)')
    parser.add_argument('--batch-size', type=int, default=1,
                       help='Questions per LLM request (default: 1, max: 3)')

    # Show help if no arguments
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    # Validate batch size
    if args.batch_size < 1 or args.batch_size > 3:
        print("ERROR: Batch size must be between 1 and 3")
        sys.exit(1)

    # Check if Ollama is running
    import requests
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=5)
        if response.status_code != 200:
            raise requests.exceptions.RequestException("Ollama not responding")
    except:
        print("ERROR: Ollama is not running or not accessible!")
        print("\nTo use local LLM question setup:")
        print("1. Install Ollama from https://ollama.ai/")
        print(f"2. Download a model: ollama pull {args.model}")
        print("3. Start Ollama (usually starts automatically)")
        print("4. Verify it's running: curl http://localhost:11434/api/tags")
        sys.exit(1)

    success = setup_questions(
        args.input_csv,
        model=args.model,
        subject=args.subject,
        keep_distractors=not args.delete_distractors,  # Invert the delete flag
        batch_size=args.batch_size
    )

    if not success:
        print("\nSetup failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()