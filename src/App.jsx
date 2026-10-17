import React, { useState } from 'react';
import SearchForm from './components/SearchForm';
import ResultCard from './components/ResultCard';
import LoadingSpinner from './components/LoadingSpinner';
import EmptyState from './components/EmptyState';
import ErrorDisplay from './components/ErrorDisplay';

function App() {
  const [query, setQuery] = useState('');
  const [keyword, setKeyword] = useState('');
  const [maxAttempts, setMaxAttempts] = useState(3);
  const [maxResults, setMaxResults] = useState(10);
  const [results, setResults] = useState([]);
  const [searchedKeyword, setSearchedKeyword] = useState('');
  const [hasSearched, setHasSearched] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const hits = results.filter((r) => r.keyword_detected === true);
  const failures = results.filter(
    (r) => r.keyword_detected !== true && /error|failed/i.test(r.reason || '')
  ).length;

  const handleSearch = async (e) => {
    e.preventDefault();
    
    if (!query.trim()) {
      setError('Please enter a search query');
      return;
    }
    
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch('http://localhost:8000/search_streams', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query, keyword, max_attempts: maxAttempts, max_results: maxResults }),
      });

      if (!response.ok) {
        throw new Error('Failed to fetch results');
      }

      const data = await response.json();
      setSearchedKeyword(keyword);
      setHasSearched(true);
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unknown error occurred');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-gray-100">
      <div className="container mx-auto px-4 py-12">
        <div className="max-w-3xl mx-auto">
          <div className="bg-white rounded-2xl shadow-xl overflow-hidden">
            {/* Header */}
            <div className="bg-gradient-to-r from-blue-500 to-indigo-600 px-6 py-6 sm:py-8">
              <h1 className="text-2xl sm:text-3xl font-bold text-white text-center">
                VoxBlitz: Streaming Search Engine
              </h1>
              <p className="text-blue-100 text-center mt-2 text-sm sm:text-base">
                Search streams and detect keywords in real-time
              </p>
            </div>
            
            {/* Content */}
            <div className="p-6">
              <SearchForm 
                query={query}
                keyword={keyword}
                isLoading={isLoading}
                onQueryChange={setQuery}
                onKeywordChange={setKeyword}
                maxAttempts={maxAttempts}
                onMaxAttemptsChange={setMaxAttempts}
                maxResults={maxResults}
                onMaxResultsChange={setMaxResults}
                onSubmit={handleSearch}
              />
              
              {error && <ErrorDisplay message={error} />}
              
              {/* Results */}
              <div className="space-y-4">
                {isLoading ? (
                  <LoadingSpinner />
                ) : hasSearched ? (
                  <div className="grid gap-4 animate-fadeIn">
                    <p className="text-sm text-gray-500">
                      {hits.length} match{hits.length === 1 ? '' : 'es'} from {results.length} live streams
                      {failures > 0 && ` (${failures} could not be fully checked, e.g. API rate limit)`}
                    </p>
                    {hits.map((result, index) => (
                      <div key={index} className="animate-fadeIn" style={{ animationDelay: `${index * 100}ms` }}>
                        <ResultCard result={result} keyword={searchedKeyword} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <EmptyState />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;