import React from 'react';
import { ExternalLink } from 'lucide-react';

const formatAgo = (seconds) => {
  if (seconds == null) return '';
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s ago`;
};

const ResultCard = ({ result, keyword }) => {
  const isVod = result.link_type === 'vod';

  // Rendered like a search-engine hit: title link, green URL line, snippet.
  return (
    <div className="p-4 rounded-xl border border-gray-100 hover:shadow-md transition-shadow">
      <p className="text-xs text-green-700 truncate">{result.link}</p>
      <a
        href={result.link}
        target="_blank"
        rel="noopener noreferrer"
        className="text-lg font-medium text-blue-700 hover:underline inline-flex items-center"
      >
        {result.user_name}: &ldquo;{keyword}&rdquo; spoken {formatAgo(result.seconds_ago)}
        <ExternalLink size={14} className="ml-1.5" />
      </a>
      <p className="text-sm text-gray-600 mt-1">
        {isVod
          ? 'Jumps to the exact moment in the stream’s VOD (approximate, within a few seconds).'
          : 'The streamer has VODs disabled, so this opens the live stream instead of the moment.'}
      </p>
    </div>
  );
};

export default ResultCard;
