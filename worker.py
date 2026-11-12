"""One background subprocess per run; native DLL cannot leak into Streamlit reruns."""
import sys
from backend import execute_job

if __name__ == "__main__":
    execute_job(sys.argv[1])
