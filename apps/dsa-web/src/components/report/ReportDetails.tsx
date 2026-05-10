import type React from 'react';
import type { ReportDetails as ReportDetailsType } from '../../types/analysis';
import { Card } from '../common';

interface ReportDetailsProps {
  details?: ReportDetailsType;
  queryId?: string;
}

/**
 * 透明度与追溯区组件 - 终端风格
 */
export const ReportDetails: React.FC<ReportDetailsProps> = ({
  details,
  queryId,
}) => {
  if (!details?.newsContent && !queryId) {
    return null;
  }

  return (
    <Card variant="bordered" padding="md" className="text-left">
      <div className="mb-3 flex items-baseline gap-2">
        <span className="label-uppercase">TRANSPARENCY</span>
        <h3 className="text-base font-semibold text-white mt-0.5">数据追溯</h3>
      </div>

      {/* Query ID */}
      {queryId && (
        <div className="flex items-center gap-2 text-xs text-muted mb-3 pb-3 border-b border-white/5">
          <span>Query ID:</span>
          <code className="font-mono text-xs text-cyan bg-cyan/10 px-1.5 py-0.5 rounded">
            {queryId}
          </code>
        </div>
      )}

      {details?.newsContent && (
        <div className="rounded-lg bg-elevated/60 border border-white/5 p-3">
          <div className="mb-2">
            <span className="label-uppercase">NEWS SNAPSHOT</span>
            <h4 className="mt-1 text-sm font-medium text-white">新闻摘要</h4>
          </div>
          <p className="text-sm text-secondary leading-relaxed whitespace-pre-wrap">
            {details.newsContent}
          </p>
        </div>
      )}
    </Card>
  );
};
