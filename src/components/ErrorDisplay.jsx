import React from 'react';
import { AlertCircle } from 'lucide-react';

const ErrorDisplay = ({ message }) => {
  return (
    <div className="flex items-center p-4 mb-6 bg-red-50 border border-red-100 rounded-lg animate-fadeIn">
      <AlertCircle size={20} className="text-red-500 mr-3 flex-shrink-0" />
      <p className="text-red-600 text-sm font-medium">{message}</p>
    </div>
  );
};

export default ErrorDisplay;