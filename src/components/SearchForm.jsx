import React from 'react';
import { Search } from 'lucide-react';

const SearchForm = ({
  query,
  keyword,
  isLoading,
  onQueryChange,
  onKeywordChange,
  onSubmit,
}) => {
  return (
    <form onSubmit={onSubmit} className="w-full mb-8">
      <div className="flex flex-col space-y-4">
        <div className="flex flex-col sm:flex-row sm:space-x-4 space-y-4 sm:space-y-0">
          <div className="flex-1 relative">
            <input
              type="text"
              placeholder="Enter search query..."
              value={query}
              onChange={(e) => onQueryChange(e.target.value)}
              className="w-full p-3.5 pl-11 rounded-xl border border-gray-200 bg-white text-sky-500/90 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200"
              disabled={isLoading}
            />
            <div className="absolute inset-y-0 left-0 flex items-center pl-3 pointer-events-none text-gray-400">
              <Search size={18} />
            </div>
          </div>
          
          <div className="flex-1 relative">
            <input
              type="text"
              placeholder="Enter keyword..."
              value={keyword}
              onChange={(e) => onKeywordChange(e.target.value)}
              className="w-full p-3.5 rounded-xl border border-gray-200 bg-white text-sky-500/90 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200"
              disabled={isLoading}
            />
          </div>
        </div>
        
        {/* <button
          type="submit"
          disabled={isLoading}
          className="w-full sm:w-auto sm:self-end py-3.5 px-6 bg-gradient-to-r from-blue-500 to-indigo-600 text-white font-medium rounded-xl hover:from-blue-600 hover:to-indigo-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all duration-200 disabled:opacity-70 disabled:cursor-not-allowed disabled:hover:from-blue-500 disabled:hover:to-indigo-600"
        > */}
          <button
  type="submit"
  disabled={isLoading}
  className="w-full sm:w-auto mx-auto py-3.5 px-6 bg-gradient-to-r from-blue-500 to-indigo-600 text-white font-medium rounded-xl hover:from-blue-600 hover:to-indigo-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 transition-all duration-200 disabled:opacity-70 disabled:cursor-not-allowed disabled:hover:from-blue-500 disabled:hover:to-indigo-600"
>

          {isLoading ? (
            <span className="flex items-center justify-center">
              <span className="mr-2">Searching</span>
              <span className="flex space-x-1">
                <span className="w-1.5 h-1.5 bg-white rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></span>
                <span className="w-1.5 h-1.5 bg-white rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></span>
                <span className="w-1.5 h-1.5 bg-white rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></span>
              </span>
            </span>
          ) : (
            'Search Streams'
          )}
        </button>
      </div>
    </form>
  );
};

export default SearchForm;