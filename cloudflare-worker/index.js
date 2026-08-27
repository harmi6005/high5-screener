/**
 * high5-screener 텔레그램 웹훅 → GitHub repository_dispatch 브릿지
 *
 * ⚠️ 이 파일은 high5-screener 저장소가 아니라 별도의 Cloudflare Worker 프로젝트로
 * 배포하는 코드입니다 (wrangler CLI 사용). GitHub Actions에서는 실행되지 않습니다.
 *
 * 모든 민감정보(GITHUB_PAT, GITHUB_OWNER, GITHUB_REPO, ALLOWED_CHAT_ID)는
 * 코드에 하드코딩하지 않고 전부 Worker 환경변수(Secret)로만 참조합니다.
 * (터틀 프로젝트에서 겪었던 "대시보드 Quick Edit로는 Secret이 반영 안 되는 문제"를
 * 피하기 위해, 반드시 wrangler CLI의 `wrangler secret put`으로 등록해야 합니다.)
 */

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('OK - use POST for telegram webhook', { status: 200 });
    }

    let body;
    try {
      body = await request.json();
    } catch (e) {
      return new Response('bad request', { status: 400 });
    }

    const message = body.message || body.edited_message;
    if (!message || !message.text) {
      return new Response('ignored (no text message)', { status: 200 });
    }

    // 등록된 chat_id가 아니면 무시 (다른 사람이 봇에게 말 걸어도 반응 안 함)
    if (String(message.chat.id) !== env.ALLOWED_CHAT_ID) {
      return new Response('ignored (unauthorized chat_id)', { status: 200 });
    }

    const githubResponse = await fetch(
      `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/dispatches`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'Accept': 'application/vnd.github+json',
          'User-Agent': 'high5-webhook-worker',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          event_type: 'telegram_message',
          client_payload: { text: message.text },
        }),
      }
    );

    return new Response(`GitHub API status: ${githubResponse.status}`, { status: 200 });
  },
};
