import React from 'react';
import { Search } from 'lucide-react';

const EmptyState = () => {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      <div className="w-16 h-16 bg-gray-50 rounded-full flex items-center justify-center mb-4">
        <Search size={28} className="text-gray-400" />
      </div>
      <h3 className="text-lg font-medium text-gray-700 mb-2">No results yet</h3>
      <p className="text-gray-500 max-w-sm">
        Enter a query and keyword above to search for streams and detect keyword matches.
      </p>
    </div>
  );
};

export default EmptyState;