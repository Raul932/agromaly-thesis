import 'package:flutter/material.dart';
import '../services/chat_service.dart';

/// Global AI Agronomist — a full-screen conversational assistant
/// powered by the backend's RAG pipeline (POST /api/v1/chat/ask).
///
/// If the RAG endpoint is not yet deployed, the screen gracefully
/// displays an "AI backend not connected" message while keeping
/// the UI fully functional for demo / thesis purposes.
class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen>
    with SingleTickerProviderStateMixin {
  final TextEditingController _inputController = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  final List<_ChatMessage> _messages = [];
  final List<Map<String, String>> _history = [];
  bool _isSending = false;

  // Suggested starter questions
  static const _starters = [
    'What causes NDVI anomalies in wheat fields?',
    'How should I treat corn affected by drought stress?',
    'What is the optimal fertilization schedule for sunflowers?',
    'When is the best time to apply pesticides?',
  ];

  @override
  void initState() {
    super.initState();
    // Greeting message from the AI
    _messages.add(
      _ChatMessage(
        text:
            'Hello! I am your AI Agronomist powered by the Agromaly RAG pipeline. '
            'I can answer questions about crop health, pest management, irrigation, '
            'soil science, and agronomic best practices.\n\n'
            'What would you like to know today?',
        isUser: false,
        timestamp: DateTime.now(),
      ),
    );
  }

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  Future<void> _sendMessage(String text) async {
    if (text.trim().isEmpty || _isSending) return;

    final userMsg = _ChatMessage(
      text: text.trim(),
      isUser: true,
      timestamp: DateTime.now(),
    );

    setState(() {
      _messages.add(userMsg);
      _isSending = true;
      _inputController.clear();
    });

    _scrollToBottom();

    try {
      final answer = await ChatService.askGlobal(
        text.trim(),
        List.from(_history),
      );

      _history.add({'role': 'user', 'content': text.trim()});
      _history.add({'role': 'assistant', 'content': answer});

      setState(() {
        _messages.add(_ChatMessage(
          text: answer,
          isUser: false,
          timestamp: DateTime.now(),
        ));
        _isSending = false;
      });
    } catch (e) {
      setState(() {
        _messages.add(_ChatMessage(
          text: 'Could not reach the AI service. '
              '${e.toString().replaceFirst("Exception: ", "")}',
          isUser: false,
          timestamp: DateTime.now(),
          isOffline: true,
        ));
        _isSending = false;
      });
    }

    _scrollToBottom();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeOut,
        );
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0D1B2A),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0D1B2A),
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_ios, color: Colors.white70),
          onPressed: () => Navigator.of(context).pop(),
        ),
        title: const Row(
          children: [
            Icon(Icons.smart_toy, color: Color(0xFF52B788), size: 22),
            SizedBox(width: 10),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'AI Agronomist',
                  style: TextStyle(
                    color: Colors.white,
                    fontSize: 16,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                Text(
                  'RAG-powered crop advisor',
                  style: TextStyle(
                    color: Colors.white38,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.delete_outline, color: Colors.white38),
            tooltip: 'Clear conversation',
            onPressed: () => setState(() {
              _messages.clear();
              _messages.add(_ChatMessage(
                text: 'Conversation cleared. How can I help you today?',
                isUser: false,
                timestamp: DateTime.now(),
              ));
            }),
          ),
        ],
      ),
      body: Column(
        children: [
          // Chat messages
          Expanded(
            child: ListView.builder(
              controller: _scrollController,
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
              itemCount: _messages.length + (_isSending ? 1 : 0),
              itemBuilder: (context, index) {
                if (index == _messages.length) {
                  return _typingIndicator();
                }
                return _chatBubble(_messages[index]);
              },
            ),
          ),

          // Starter suggestions (only when fresh)
          if (_messages.length == 1) _starterSuggestions(),

          // Input row
          _inputBar(),
        ],
      ),
    );
  }

  Widget _chatBubble(_ChatMessage msg) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        mainAxisAlignment:
            msg.isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (!msg.isUser) ...[
            Container(
              width: 32,
              height: 32,
              margin: const EdgeInsets.only(right: 8, bottom: 2),
              decoration: BoxDecoration(
                color: const Color(0xFF52B788).withValues(alpha: 0.2),
                shape: BoxShape.circle,
              ),
              child: const Icon(
                Icons.smart_toy,
                color: Color(0xFF52B788),
                size: 17,
              ),
            ),
          ],
          Flexible(
            child: Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              decoration: BoxDecoration(
                color: msg.isUser
                    ? const Color(0xFF52B788).withValues(alpha: 0.85)
                    : Colors.white.withValues(alpha: 0.06),
                borderRadius: BorderRadius.only(
                  topLeft: const Radius.circular(18),
                  topRight: const Radius.circular(18),
                  bottomLeft: msg.isUser
                      ? const Radius.circular(18)
                      : const Radius.circular(4),
                  bottomRight: msg.isUser
                      ? const Radius.circular(4)
                      : const Radius.circular(18),
                ),
                border: msg.isUser
                    ? null
                    : Border.all(
                        color: msg.isOffline
                            ? const Color(0xFFE9C46A).withValues(alpha: 0.2)
                            : Colors.white.withValues(alpha: 0.08),
                      ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    msg.text,
                    style: TextStyle(
                      color: msg.isUser ? Colors.white : Colors.white70,
                      fontSize: 14,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    _formatTime(msg.timestamp),
                    style: TextStyle(
                      color: msg.isUser
                          ? Colors.white.withValues(alpha: 0.5)
                          : Colors.white24,
                      fontSize: 10,
                    ),
                  ),
                ],
              ),
            ),
          ),
          if (msg.isUser) const SizedBox(width: 8),
        ],
      ),
    );
  }

  Widget _typingIndicator() {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          Container(
            width: 32,
            height: 32,
            margin: const EdgeInsets.only(right: 8),
            decoration: BoxDecoration(
              color: const Color(0xFF52B788).withValues(alpha: 0.2),
              shape: BoxShape.circle,
            ),
            child: const Icon(Icons.smart_toy,
                color: Color(0xFF52B788), size: 17),
          ),
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.06),
              borderRadius: BorderRadius.circular(18),
              border:
                  Border.all(color: Colors.white.withValues(alpha: 0.08)),
            ),
            child: const SizedBox(
              width: 36,
              height: 16,
              child: _TypingDots(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _starterSuggestions() {
    return Container(
      height: 44,
      margin: const EdgeInsets.only(bottom: 8),
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16),
        itemCount: _starters.length,
        separatorBuilder: (_, __) => const SizedBox(width: 8),
        itemBuilder: (context, i) => ActionChip(
          label: Text(
            _starters[i],
            style: const TextStyle(
              color: Color(0xFF52B788),
              fontSize: 12,
            ),
          ),
          backgroundColor: const Color(0xFF52B788).withValues(alpha: 0.1),
          side: BorderSide(
            color: const Color(0xFF52B788).withValues(alpha: 0.3),
          ),
          onPressed: () => _sendMessage(_starters[i]),
        ),
      ),
    );
  }

  Widget _inputBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(12, 8, 8, 16),
      decoration: BoxDecoration(
        color: const Color(0xFF0D1B2A),
        border: Border(
          top: BorderSide(color: Colors.white.withValues(alpha: 0.08)),
        ),
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _inputController,
              style: const TextStyle(color: Colors.white, fontSize: 14),
              decoration: InputDecoration(
                hintText: 'Ask the AI Agronomist...',
                hintStyle:
                    const TextStyle(color: Colors.white38, fontSize: 14),
                filled: true,
                fillColor: Colors.white.withValues(alpha: 0.05),
                contentPadding: const EdgeInsets.symmetric(
                    horizontal: 16, vertical: 12),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                  borderSide: BorderSide.none,
                ),
                focusedBorder: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(24),
                  borderSide: BorderSide(
                    color: const Color(0xFF52B788).withValues(alpha: 0.5),
                  ),
                ),
              ),
              onSubmitted: _sendMessage,
              textInputAction: TextInputAction.send,
              maxLines: null,
            ),
          ),
          const SizedBox(width: 8),
          AnimatedContainer(
            duration: const Duration(milliseconds: 200),
            child: FloatingActionButton.small(
              heroTag: 'chat_send',
              backgroundColor: _isSending
                  ? Colors.white12
                  : const Color(0xFF52B788),
              elevation: 0,
              onPressed: _isSending
                  ? null
                  : () => _sendMessage(_inputController.text),
              child: _isSending
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white38,
                      ),
                    )
                  : const Icon(Icons.send_rounded,
                      color: Colors.white, size: 18),
            ),
          ),
        ],
      ),
    );
  }

  String _formatTime(DateTime dt) {
    final h = dt.hour.toString().padLeft(2, '0');
    final m = dt.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }
}

/// Animated three-dot typing indicator.
class _TypingDots extends StatefulWidget {
  const _TypingDots();

  @override
  State<_TypingDots> createState() => _TypingDotsState();
}

class _TypingDotsState extends State<_TypingDots>
    with SingleTickerProviderStateMixin {
  late AnimationController _ctrl;

  @override
  void initState() {
    super.initState();
    _ctrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    )..repeat();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _ctrl,
      builder: (_, __) {
        return Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: List.generate(3, (i) {
            final phase = ((_ctrl.value * 3) - i).clamp(0.0, 1.0);
            final opacity = (phase < 0.5 ? phase * 2 : (1 - phase) * 2)
                .clamp(0.3, 1.0);
            return Container(
              margin: const EdgeInsets.symmetric(horizontal: 2),
              width: 7,
              height: 7,
              decoration: BoxDecoration(
                color: const Color(0xFF52B788).withValues(alpha: opacity),
                shape: BoxShape.circle,
              ),
            );
          }),
        );
      },
    );
  }
}

class _ChatMessage {
  final String text;
  final bool isUser;
  final DateTime timestamp;
  final bool isOffline;

  const _ChatMessage({
    required this.text,
    required this.isUser,
    required this.timestamp,
    this.isOffline = false,
  });
}
