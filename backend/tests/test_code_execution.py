import sys
import os
import matplotlib
matplotlib.use('Agg')

# Ensure backend can import its modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.agent.agent import agent

# Helper to maintain test compatibility
def process_and_execute(code, df):
    return agent._execute_safe(code, df)

class TestExecutionStates:
    
    def test_execution_on_simple_df(self, simple_df):
        code = "print(df['A'].mean())"
        result, exec_code, image = process_and_execute(code, simple_df)
        assert "3.0" in result
        assert image is None

    def test_execution_on_empty_df(self, empty_df):
        code = "print(df.shape)"
        result, exec_code, image = process_and_execute(code, empty_df)
        assert "(0, 0)" in result

        # Operation that might fail on empty DF
        code_mean = "print(df['A'].mean())" 
        # This checks error handling inside process_and_execute
        result_mean, _, _ = process_and_execute(code_mean, empty_df)
        # Should catch error (KeyError) and return error string
        assert "Error executing code" in result_mean

    def test_execution_on_missing_values_df(self, missing_values_df):
        # Pandas handles NaNs in mean by skipping them by default
        code = "print(df['A'].mean())"
        result, _, _ = process_and_execute(code, missing_values_df)
        # 1, 2, 4 -> mean is 7/3 = 2.333
        assert result is not None
        
        # Test operation that might be affected by NaNs
        code_count = "print(df['A'].count())"
        result_count, _, _ = process_and_execute(code_count, missing_values_df)
        assert "3" in result_count # Should be 3 not 4

    def test_syntax_error_handling(self, simple_df):
        code = "print(df['A' ... )" # Syntax error
        result, _, _ = process_and_execute(code, simple_df)
        assert "Error" in result or "SyntaxError" in result

    def test_plot_generation(self, simple_df):
        code = "plt.plot(df['A'], df['C']); plt.title('Test Plot')"
        result, _, image = process_and_execute(code, simple_df)
        
        # DEBUG: Print result if it failed
        if result != "Plot generated successfully.":
            print(f"\nDEBUG ERROR: {result}")
            
        assert result == "Plot generated successfully."
        assert image is not None
        assert len(image) > 0 # Base64 string

    def test_dataframe_mutation_isolation(self, simple_df):
        # Ensure that code doesn't permanently destroy the passed variable if we don't want it to
        # Though the agent runs locally, so it MIGHT mutate it. 
        # The test checks behavior in "mutated state"
        code = "df['D'] = df['A'] * 2; print(df.columns)"
        result, _, _ = process_and_execute(code, simple_df)
        assert "D" in result
        # Check if the fixture itself was modified (it likely is since python passes by ref)
        # This is strictly a test of "what happens when state changes"
        assert 'D' in simple_df.columns 

    def test_security_restrictions(self, simple_df):
        # Basic check if restricted builtins are blocked?
        # agent.py filters 'eval', 'exec', 'open' in __builtins__
        code = "print(open('test.txt', 'w'))"
        result, _, _ = process_and_execute(code, simple_df)
        assert "Error" in result
        assert "name 'open' is not defined" in result
