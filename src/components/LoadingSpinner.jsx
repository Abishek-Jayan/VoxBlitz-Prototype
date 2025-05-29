import React from 'react';

const LoadingSpinner = () => {
  return (
    <div className="flex flex-col items-center justify-center py-8">
      <div className="relative w-16 h-16">
        <div className="absolute top-0 left-0 w-full h-full border-4 border-blue-200 rounded-full opacity-25"></div>
        <div className="absolute top-0 left-0 w-full h-full border-4 border-transparent border-t-blue-600 rounded-full animate-spin"></div>
      </div>
      <p className="mt-4 text-sm text-gray-500 font-medium">Searching streams...</p>
    </div>
  );
};

export default LoadingSpinner;