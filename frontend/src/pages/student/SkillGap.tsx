import { useState, useEffect } from "react";
import { PageHeader } from "../../components/layout/PageHeader";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "../../components/ui/card";
import { SkillGapRadar } from "../../components/charts/SkillGapRadar";
import { Alert, AlertDescription } from "../../components/ui/alert";
import { Loader2, TrendingUp, TrendingDown, Minus, AlertCircle } from "lucide-react";
import { useAuth } from "../../hooks/useAuth";

interface GapItem {
  topic_id: number;
  topic_name: string;
  accuracy: number;
  severity: string;
  priority: number;
  classification: string;
  trend: string | null;
  evidence: string;
  reason: string;
  recommended_action: string;
  confidence: string;
}

interface SkillGapReport {
  id: number;
  attempt_id: number;
  level_id: number;
  created_at: string;
  summary: string;
  overall_performance: string;
  recommendations: any[];
  study_plan: any[];
  next_level_readiness: string;
  next_level_id: number | null;
  confidence: string;
  confidence_factors: string[];
  llm_interpretation: string | null;
  gaps: GapItem[];
}

export function SkillGap() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<SkillGapReport | null>(null);

  useEffect(() => {
    if (user) {
      fetchSkillGapAnalysis();
    }
  }, [user]);

  const fetchSkillGapAnalysis = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await fetch('/api/v1/ai-engine/skill-gap/latest', {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      });

      if (!response.ok) {
        throw new Error('Failed to fetch skill gap analysis');
      }

      const data = await response.json();

      if (data.success && data.exists) {
        setReport(data.report);
      } else {
        setReport(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load analysis');
    } finally {
      setLoading(false);
    }
  };

  // Build radar data from actual gap items
  const radarData = report?.gaps
    ? report.gaps.map(gap => ({
        subject: gap.topic_name,
        A: Math.round(gap.accuracy * 100),
        fullMark: 100
      }))
    : [];

  // Separate gaps by severity
  const highSeverityGaps = report?.gaps.filter(g => g.severity === 'HIGH') || [];
  const mediumSeverityGaps = report?.gaps.filter(g => g.severity === 'MEDIUM') || [];
  const lowSeverityGaps = report?.gaps.filter(g => g.severity === 'LOW') || [];

  // Get trend icon
  const getTrendIcon = (trend: string | null) => {
    if (trend === 'IMPROVING') return <TrendingUp className="h-4 w-4 text-green-600" />;
    if (trend === 'DECLINING') return <TrendingDown className="h-4 w-4 text-red-600" />;
    if (trend === 'STABLE') return <Minus className="h-4 w-4 text-gray-600" />;
    return null;
  };

  // Get severity color
  const getSeverityColor = (severity: string) => {
    if (severity === 'HIGH') return 'text-red-600 bg-red-50 border-red-200';
    if (severity === 'MEDIUM') return 'text-orange-600 bg-orange-50 border-orange-200';
    return 'text-yellow-600 bg-yellow-50 border-yellow-200';
  };

  // Get readiness badge color
  const getReadinessColor = (readiness: string) => {
    if (readiness === 'READY') return 'bg-green-100 text-green-800';
    if (readiness === 'NEEDS_TARGETED_PREPARATION') return 'bg-orange-100 text-orange-800';
    if (readiness === 'SIGNIFICANT_GAPS') return 'bg-red-100 text-red-800';
    return 'bg-gray-100 text-gray-800';
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader
          title="Skill Gap Analysis"
          description="Personalized learning recommendations based on your performance"
        />
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader
          title="Skill Gap Analysis"
          description="Personalized learning recommendations based on your performance"
        />
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    );
  }

  if (!report) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageHeader
          title="Skill Gap Analysis"
          description="Personalized learning recommendations based on your performance"
        />
        <Card>
          <CardContent className="pt-6">
            <div className="text-center py-12">
              <AlertCircle className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <h3 className="text-lg font-semibold mb-2">No Analysis Available</h3>
              <p className="text-muted-foreground">
                Complete an assessment to generate your personalized Skill Gap Analysis.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Skill Gap Analysis"
        description="Personalized learning recommendations based on your performance"
      />

      {/* Summary Card */}
      <Card>
        <CardHeader>
          <CardTitle>Analysis Summary</CardTitle>
          <CardDescription>
            Generated on {new Date(report.created_at).toLocaleDateString()}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {report.summary && (
            <p className="text-sm leading-relaxed">{report.summary}</p>
          )}

          <div className="flex items-center gap-4 pt-2">
            <div>
              <span className="text-sm font-medium">Confidence: </span>
              <span className={`text-sm font-semibold ${
                report.confidence === 'HIGH' ? 'text-green-600' :
                report.confidence === 'MEDIUM' ? 'text-orange-600' :
                'text-gray-600'
              }`}>
                {report.confidence}
              </span>
            </div>

            {report.next_level_readiness && (
              <div>
                <span className="text-sm font-medium">Next Level: </span>
                <span className={`px-2 py-1 rounded text-xs font-medium ${getReadinessColor(report.next_level_readiness)}`}>
                  {report.next_level_readiness.replace(/_/g, ' ')}
                </span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Radar Chart */}
        {radarData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Topic Performance Overview</CardTitle>
              <CardDescription>
                Visual representation of your topic-level accuracy
              </CardDescription>
            </CardHeader>
            <CardContent>
              <SkillGapRadar data={radarData} />
            </CardContent>
          </Card>
        )}

        {/* LLM Interpretation */}
        {report.llm_interpretation && (
          <Card>
            <CardHeader>
              <CardTitle>Personalized Insights</CardTitle>
              <CardDescription>
                AI-generated interpretation of your performance
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-sm leading-relaxed whitespace-pre-wrap">
                {report.llm_interpretation.substring(0, 500)}
                {report.llm_interpretation.length > 500 && '...'}
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Identified Gaps */}
      {report.gaps.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-destructive">Identified Skill Gaps</CardTitle>
            <CardDescription>
              Topics requiring attention, ordered by priority
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* High Severity Gaps */}
            {highSeverityGaps.length > 0 && (
              <div className="space-y-3">
                <h4 className="text-sm font-semibold text-red-600">High Priority</h4>
                {highSeverityGaps.map((gap, idx) => (
                  <div
                    key={idx}
                    className={`p-4 rounded-lg border ${getSeverityColor(gap.severity)}`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold">#{gap.priority}</span>
                        <span className="font-medium">{gap.topic_name}</span>
                        {getTrendIcon(gap.trend)}
                      </div>
                      <span className="text-sm font-medium">
                        {Math.round(gap.accuracy * 100)}%
                      </span>
                    </div>
                    <p className="text-sm mb-2">
                      <span className="font-medium">Classification:</span> {gap.classification}
                      {gap.trend && ` • ${gap.trend}`}
                    </p>
                    <p className="text-sm text-muted-foreground">{gap.evidence}</p>
                    {gap.recommended_action && gap.recommended_action !== "See recommendations" && (
                      <p className="text-sm mt-2 font-medium">
                        → {gap.recommended_action}
                      </p>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Medium Severity Gaps */}
            {mediumSeverityGaps.length > 0 && (
              <div className="space-y-3 mt-4">
                <h4 className="text-sm font-semibold text-orange-600">Medium Priority</h4>
                {mediumSeverityGaps.slice(0, 3).map((gap, idx) => (
                  <div
                    key={idx}
                    className={`p-3 rounded-lg border ${getSeverityColor(gap.severity)}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold">#{gap.priority}</span>
                        <span className="text-sm font-medium">{gap.topic_name}</span>
                        {getTrendIcon(gap.trend)}
                      </div>
                      <span className="text-sm">{Math.round(gap.accuracy * 100)}%</span>
                    </div>
                    <p className="text-xs text-muted-foreground">{gap.evidence}</p>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Recommendations */}
      {report.recommendations && report.recommendations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Personalized Recommendations</CardTitle>
            <CardDescription>
              Actionable steps to improve your performance
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {report.recommendations.slice(0, 5).map((rec: any, idx: number) => (
                <div key={idx} className="border-l-4 border-primary pl-4 py-2">
                  <p className="font-medium text-sm">{rec.title || rec.action || JSON.stringify(rec)}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Confidence Factors */}
      {report.confidence_factors && report.confidence_factors.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Analysis Confidence Factors</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="text-sm space-y-1 text-muted-foreground">
              {report.confidence_factors.map((factor, idx) => (
                <li key={idx}>• {factor}</li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
