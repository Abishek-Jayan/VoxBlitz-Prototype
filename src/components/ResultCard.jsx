import React from 'react';
import { CheckCircle, XCircle, User } from 'lucide-react';

const ResultCard = ({ result }) => {
  const isKeywordDetected = result.keyword_detected === 'YES';

  return (
    <div className="group bg-white p-5 rounded-xl border border-gray-100 hover:shadow-lg transition-all duration-300 ease-in-out">
      <div className="flex justify-between items-center">
        <div className="flex items-center space-x-3">
          <div className="p-2 bg-gray-50 rounded-full text-blue-500 group-hover:bg-blue-50 transition-colors duration-300">
            <User size={20} />
          </div>
          <span className="text-lg font-medium text-gray-800">{result.user_name}</span>
        </div>
        
        <div className={`flex items-center px-3 py-1.5 rounded-full ${
          isKeywordDetected 
            ? 'bg-green-50 text-green-600' 
            : 'bg-red-50 text-red-600'
        } transition-colors duration-300`}>
          {isKeywordDetected ? (
            <CheckCircle size={16} className="mr-1.5" />
          ) : (
            <XCircle size={16} className="mr-1.5" />
          )}
          <span className="text-sm font-medium">
            {isKeywordDetected ? 'Keyword Detected' : 'No Keyword'}
          </span>
        </div>
      </div>
    </div>
  );
};

export default ResultCard;